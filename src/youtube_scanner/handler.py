"""
YouTube Scanner Lambda
======================
Triggered every 24 hours by CloudWatch Events.

Workflow:
  1. Fetch the @GaryEats YouTube RSS feed to find the latest video.
  2. Check DynamoDB to see if we've already processed it.
  3. If it's new, write a record with status="discovered" and invoke
     the Video Downloader Lambda asynchronously.

We use the public YouTube RSS feed (no API key required for this step):
  https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID

The YouTube API key stored in Secrets Manager is kept as a fallback
for richer metadata queries if needed in the future.
"""

import json
import os
import re
import boto3
import feedparser
import requests
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
secrets_client = boto3.client("secretsmanager")

VIDEOS_TABLE = os.environ["VIDEOS_TABLE_NAME"]
SECRET_NAME = os.environ["YOUTUBE_API_KEY_SECRET"]
CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
DOWNLOADER_FN = os.environ["VIDEO_DOWNLOADER_FUNCTION"]

# YouTube RSS feed URL — works with both @handle and UCxxxxxxxx channel IDs
YOUTUBE_RSS_BASE = "https://www.youtube.com/feeds/videos.xml"


# ── Helpers ────────────────────────────────────────────────────────────────────

def resolve_channel_id(channel_ref: str) -> str:
    """
    Convert a @Handle to a real channel ID (UC...) by scraping the channel
    page.  If it already looks like a UC ID, return it as-is.
    """
    if channel_ref.startswith("UC"):
        return channel_ref

    # Fetch the channel page and extract the canonical channel ID
    handle = channel_ref.lstrip("@")
    url = f"https://www.youtube.com/@{handle}"
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    match = re.search(r'"externalId"\s*:\s*"(UC[^"]+)"', resp.text)
    if not match:
        # Fallback: look in meta tags
        match = re.search(r'channel_id=(UC[^"&]+)', resp.text)
    if not match:
        raise ValueError(f"Could not resolve channel ID for {channel_ref}")

    channel_id = match.group(1)
    print(f"Resolved {channel_ref} → {channel_id}")
    return channel_id


def fetch_latest_videos(channel_id: str, max_results: int = 5) -> list[dict]:
    """Fetch the latest videos from the YouTube RSS feed."""
    feed_url = f"{YOUTUBE_RSS_BASE}?channel_id={channel_id}"
    print(f"Fetching RSS feed: {feed_url}")

    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        raise RuntimeError(f"Failed to parse RSS feed: {feed.bozo_exception}")

    videos = []
    for entry in feed.entries[:max_results]:
        video_id = entry.get("yt_videoid", "")
        if not video_id:
            # Extract from link
            link = entry.get("link", "")
            if "v=" in link:
                video_id = link.split("v=")[-1].split("&")[0]

        videos.append({
            "video_id": video_id,
            "title": entry.get("title", "Untitled"),
            "published_at": entry.get("published", datetime.now(timezone.utc).isoformat()),
            "link": entry.get("link", ""),
            "author": entry.get("author", "GaryEats"),
            "summary": entry.get("summary", ""),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else None,
        })

    return videos


def is_already_known(video_id: str) -> bool:
    """Check if this video_id already exists in DynamoDB."""
    table = dynamodb.Table(VIDEOS_TABLE)
    resp = table.get_item(Key={"video_id": video_id}, ProjectionExpression="video_id")
    return "Item" in resp


def save_video_record(video: dict) -> None:
    """Write a new video record to DynamoDB with status=discovered."""
    table = dynamodb.Table(VIDEOS_TABLE)
    now = datetime.now(timezone.utc).isoformat()
    table.put_item(Item={
        "video_id": video["video_id"],
        "title": video["title"],
        "original_url": video["link"],
        "thumbnail": video.get("thumbnail", ""),
        "author": video.get("author", ""),
        "summary": video.get("summary", ""),
        "published_at": video["published_at"],
        "status": "discovered",
        "discovered_at": now,
        "updated_at": now,
    })


def invoke_downloader(video: dict) -> None:
    """Asynchronously invoke the Video Downloader Lambda."""
    payload = {
        "video_id": video["video_id"],
        "video_url": video["link"],
        "title": video["title"],
    }
    print(f"Invoking downloader for {video['video_id']}: {video['title']}")
    lambda_client.invoke(
        FunctionName=DOWNLOADER_FN,
        InvocationType="Event",  # async
        Payload=json.dumps(payload).encode(),
    )


# ── Handler ────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Scan @GaryEats channel for new videos via RSS feed.
    For each unseen video, save it and kick off the download pipeline.
    """
    print(f"YouTube Scanner triggered at {datetime.now(timezone.utc).isoformat()}")
    print(f"Channel reference: {CHANNEL_ID}")

    try:
        # Step 1 — Resolve handle → channel ID
        real_channel_id = resolve_channel_id(CHANNEL_ID)

        # Step 2 — Fetch latest videos from RSS
        latest = fetch_latest_videos(real_channel_id)
        print(f"Found {len(latest)} videos in RSS feed")

        new_count = 0
        for video in latest:
            vid = video["video_id"]
            if not vid:
                print("  Skipping entry with no video ID")
                continue

            if is_already_known(vid):
                print(f"  Already known: {vid} — {video['title']}")
                continue

            # Step 3 — New video! Save and trigger download
            print(f"  NEW video: {vid} — {video['title']}")
            save_video_record(video)
            invoke_downloader(video)
            new_count += 1

        summary = {
            "scanned": len(latest),
            "new_videos": new_count,
            "channel": CHANNEL_ID,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(f"Scan complete: {json.dumps(summary)}")
        return {"statusCode": 200, "body": json.dumps(summary)}

    except Exception as e:
        print(f"ERROR in YouTube Scanner: {e}")
        raise
