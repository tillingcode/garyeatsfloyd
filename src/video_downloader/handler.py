"""
Video Downloader Lambda
=======================
Invoked asynchronously by the YouTube Scanner.

Workflow:
  1. Receive video_id + video_url from the scanner.
  2. Update DynamoDB status to "downloading".
  3. Fetch video metadata via YouTube oEmbed API and download the thumbnail.
  4. Upload the thumbnail to the raw-videos S3 bucket.
  5. Create a processing job record in DynamoDB.
  6. Invoke the Video Processor Lambda asynchronously.

Note: We do NOT download the full video because Bedrock Nova Reel uses
TEXT_VIDEO generation (creates from a text prompt), so the raw video file
is not needed. We store metadata + thumbnail for the website display.
"""

import json
import os
import uuid
import boto3
import requests
from datetime import datetime, timezone

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

RAW_BUCKET = os.environ["RAW_VIDEOS_BUCKET"]
VIDEOS_TABLE = os.environ["VIDEOS_TABLE_NAME"]
JOBS_TABLE = os.environ["JOBS_TABLE_NAME"]
PROCESSOR_FN = os.environ["VIDEO_PROCESSOR_FUNCTION"]

DOWNLOAD_DIR = "/tmp/downloads"


# ── Helpers ────────────────────────────────────────────────────────────────────

def update_video_status(video_id: str, status: str, extra: dict | None = None):
    """Update the video record status in DynamoDB."""
    table = dynamodb.Table(VIDEOS_TABLE)
    update_expr = "SET #s = :status, updated_at = :now"
    expr_values = {
        ":status": status,
        ":now": datetime.now(timezone.utc).isoformat(),
    }
    expr_names = {"#s": "status"}

    if extra:
        for key, val in extra.items():
            update_expr += f", {key} = :{key}"
            expr_values[f":{key}"] = val

    table.update_item(
        Key={"video_id": video_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
        ExpressionAttributeNames=expr_names,
    )


def fetch_video_metadata(video_id: str, video_url: str) -> dict:
    """
    Fetch video metadata via YouTube's oEmbed API (no API key required).
    Returns dict with title, author, thumbnail info.
    """
    oembed_url = f"https://www.youtube.com/oembed?url={video_url}&format=json"
    print(f"Fetching oEmbed metadata: {oembed_url}")

    resp = requests.get(oembed_url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (compatible; GaryEatsFloyd/1.0)"
    })
    resp.raise_for_status()
    data = resp.json()

    return {
        "title": data.get("title", "Untitled"),
        "author_name": data.get("author_name", "GaryEats"),
        "author_url": data.get("author_url", ""),
        "thumbnail_url": data.get("thumbnail_url", ""),
        "thumbnail_width": data.get("thumbnail_width", 0),
        "thumbnail_height": data.get("thumbnail_height", 0),
    }


def download_thumbnail(video_id: str, thumbnail_url: str | None = None) -> str | None:
    """
    Download the video thumbnail. Tries maxresdefault first,
    falls back to hqdefault, then oEmbed thumbnail URL.
    Returns the local file path or None.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # Ordered list of thumbnail URLs to try
    urls_to_try = [
        f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
    ]
    if thumbnail_url:
        urls_to_try.append(thumbnail_url)

    for url in urls_to_try:
        try:
            resp = requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (compatible; GaryEatsFloyd/1.0)"
            })
            if resp.status_code == 200 and len(resp.content) > 1000:
                filepath = os.path.join(DOWNLOAD_DIR, f"{video_id}_thumb.jpg")
                with open(filepath, "wb") as f:
                    f.write(resp.content)
                print(f"Thumbnail downloaded: {url} ({len(resp.content)} bytes)")
                return filepath
        except Exception as e:
            print(f"  Thumbnail fetch failed for {url}: {e}")
            continue

    print("WARNING: No thumbnail could be downloaded")
    return None


def upload_thumbnail_to_s3(filepath: str, video_id: str) -> str:
    """Upload the thumbnail to S3. Returns the S3 key."""
    s3_key = f"thumbnails/{video_id}.jpg"

    print(f"Uploading thumbnail to s3://{RAW_BUCKET}/{s3_key}")
    s3.upload_file(
        filepath,
        RAW_BUCKET,
        s3_key,
        ExtraArgs={"ContentType": "image/jpeg"},
    )

    os.remove(filepath)
    return s3_key


def save_metadata_to_s3(video_id: str, metadata: dict) -> str:
    """Save video metadata as JSON to S3. Returns the S3 key."""
    s3_key = f"metadata/{video_id}.json"
    body = json.dumps(metadata, indent=2, default=str)

    print(f"Saving metadata to s3://{RAW_BUCKET}/{s3_key}")
    s3.put_object(
        Bucket=RAW_BUCKET,
        Key=s3_key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
    )

    return s3_key


def create_processing_job(video_id: str, metadata_key: str) -> str:
    """Create a processing job record in DynamoDB. Returns job_id."""
    table = dynamodb.Table(JOBS_TABLE)
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    table.put_item(Item={
        "job_id": job_id,
        "video_id": video_id,
        "job_status": "pending",
        "raw_s3_key": metadata_key,
        "raw_bucket": RAW_BUCKET,
        "created_at": now,
        "updated_at": now,
    })

    print(f"Created processing job: {job_id}")
    return job_id


def invoke_processor(video_id: str, job_id: str, metadata_key: str, title: str):
    """Asynchronously invoke the Video Processor Lambda."""
    payload = {
        "video_id": video_id,
        "job_id": job_id,
        "raw_s3_key": metadata_key,
        "raw_bucket": RAW_BUCKET,
        "title": title,
    }
    print(f"Invoking video processor for job {job_id}")
    lambda_client.invoke(
        FunctionName=PROCESSOR_FN,
        InvocationType="Event",
        Payload=json.dumps(payload).encode(),
    )


# ── Handler ────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Fetch YouTube video metadata + thumbnail and kick off Bedrock processing.
    Expected event: { video_id, video_url, title }
    """
    video_id = event["video_id"]
    video_url = event["video_url"]
    title = event.get("title", "Untitled")

    print(f"Video Downloader invoked: {video_id} -- {title}")

    try:
        # Step 1 -- Mark as downloading
        update_video_status(video_id, "downloading")

        # Step 2 -- Fetch metadata via oEmbed
        metadata = fetch_video_metadata(video_id, video_url)
        # Use oEmbed title if scanner title was generic
        if metadata.get("title") and title == "Untitled":
            title = metadata["title"]

        # Step 3 -- Download thumbnail
        thumb_path = download_thumbnail(video_id, metadata.get("thumbnail_url"))
        thumb_s3_key = None
        if thumb_path:
            thumb_s3_key = upload_thumbnail_to_s3(thumb_path, video_id)

        # Step 4 -- Save full metadata to S3
        metadata["video_id"] = video_id
        metadata["video_url"] = video_url
        metadata["original_title"] = title
        metadata_key = save_metadata_to_s3(video_id, metadata)

        # Step 5 -- Update video record
        update_video_status(video_id, "downloaded", extra={
            "raw_s3_key": metadata_key,
            "raw_bucket": RAW_BUCKET,
            "thumbnail_s3_key": thumb_s3_key or "",
        })

        # Step 6 -- Create processing job and invoke processor
        job_id = create_processing_job(video_id, metadata_key)
        invoke_processor(video_id, job_id, metadata_key, title)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "video_id": video_id,
                "metadata_key": metadata_key,
                "thumbnail_key": thumb_s3_key,
                "job_id": job_id,
                "message": "metadata fetched, processing started",
            }),
        }

    except Exception as e:
        print(f"ERROR fetching metadata for video {video_id}: {e}")
        update_video_status(video_id, "download_error", extra={
            "error_message": str(e)[:500],
        })
        raise
