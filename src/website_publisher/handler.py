"""
Website Publisher Lambda
========================
Invoked asynchronously by the Video Processor.

Workflow:
  1. Receive video_id + processed_s3_key from the processor.
  2. Update the video record status to "published".
  3. Generate an updated videos.json manifest and upload it to the
     website S3 bucket — the React frontend reads this via the API.
  4. Update the website-content table with the published entry.
  5. Invalidate the CloudFront cache so the new video appears immediately.
"""

import json
import os
import time
import uuid
import boto3
from datetime import datetime, timezone
from decimal import Decimal

s3 = boto3.client("s3")
cloudfront = boto3.client("cloudfront")
dynamodb = boto3.resource("dynamodb")

WEBSITE_BUCKET = os.environ["WEBSITE_BUCKET"]
PROCESSED_BUCKET = os.environ["PROCESSED_VIDEOS_BUCKET"]
VIDEOS_TABLE = os.environ["VIDEOS_TABLE_NAME"]
CONTENT_TABLE = os.environ["CONTENT_TABLE_NAME"]
CF_DISTRIBUTION_ID = os.environ["CLOUDFRONT_DISTRIBUTION_ID"]
DOMAIN = os.environ["WEBSITE_DOMAIN"]


# ── Helpers ────────────────────────────────────────────────────────────────────

class DecimalEncoder(json.JSONEncoder):
    """Handle DynamoDB Decimal types during JSON serialization."""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def update_video_status(video_id: str, status: str, extra: dict | None = None):
    """Update video record status in DynamoDB."""
    table = dynamodb.Table(VIDEOS_TABLE)
    update_expr = "SET #s = :status, updated_at = :now"
    expr_values = {":status": status, ":now": datetime.now(timezone.utc).isoformat()}
    expr_names = {"#s": "status"}

    if extra:
        for k, v in extra.items():
            update_expr += f", {k} = :{k}"
            expr_values[f":{k}"] = v

    table.update_item(
        Key={"video_id": video_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
        ExpressionAttributeNames=expr_names,
    )


def get_all_published_videos() -> list[dict]:
    """
    Query DynamoDB for all videos with status=published,
    sorted by published_at descending.
    """
    table = dynamodb.Table(VIDEOS_TABLE)
    response = table.query(
        IndexName="status-published-index",
        KeyConditionExpression="#s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "published"},
        ScanIndexForward=False,  # newest first
    )
    return response.get("Items", [])


def generate_videos_manifest(videos: list[dict]) -> dict:
    """
    Build a JSON manifest of all published videos for the frontend.
    The React app fetches /api/videos which reads from DynamoDB,
    but we also upload a static manifest as a fallback.
    """
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(videos),
        "videos": [],
    }

    for v in videos:
        manifest["videos"].append({
            "video_id": v.get("video_id"),
            "title": v.get("title", "Untitled"),
            "description": v.get("summary", ""),
            "thumbnail": f"https://{DOMAIN}/thumbnails/{v['video_id']}.jpg",
            "video_url": f"https://{DOMAIN}/videos/{v['video_id']}.mp4",
            "status": "published",
            "published_at": v.get("published_at", ""),
            "original_channel": v.get("author", "@GaryEats"),
        })

    return manifest


def upload_manifest(manifest: dict):
    """Upload videos.json to the website bucket."""
    body = json.dumps(manifest, cls=DecimalEncoder, indent=2)
    s3.put_object(
        Bucket=WEBSITE_BUCKET,
        Key="data/videos.json",
        Body=body.encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-cache, no-store, must-revalidate",
    )
    print(f"Uploaded data/videos.json ({len(manifest['videos'])} videos)")


def update_content_record(video_id: str, title: str):
    """Mark the content record as published."""
    table = dynamodb.Table(CONTENT_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    table.update_item(
        Key={"content_id": video_id, "content_type": "processed_video"},
        UpdateExpression="SET published = :t, published_at = :now, updated_at = :now",
        ExpressionAttributeValues={
            ":t": True,
            ":now": now,
        },
    )


def invalidate_cloudfront(paths: list[str] | None = None):
    """Invalidate CloudFront cache for the given paths (default: everything)."""
    if not paths:
        paths = ["/*"]

    print(f"Invalidating CloudFront distribution {CF_DISTRIBUTION_ID}: {paths}")
    cloudfront.create_invalidation(
        DistributionId=CF_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"publish-{uuid.uuid4().hex[:12]}",
        },
    )


# ── Handler ────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Publish a processed video to the website.

    Expected event: { video_id, processed_s3_key, title }
    """
    video_id = event["video_id"]
    processed_key = event.get("processed_s3_key", "")
    title = event.get("title", "Untitled")

    print(f"Website Publisher invoked: {video_id} — {title}")

    try:
        # Step 1 — Update video status to published
        update_video_status(video_id, "published", extra={
            "published_to_website_at": datetime.now(timezone.utc).isoformat(),
        })

        # Step 2 — Update content record
        update_content_record(video_id, title)

        # Step 3 — Regenerate the videos manifest with all published videos
        published_videos = get_all_published_videos()
        manifest = generate_videos_manifest(published_videos)
        upload_manifest(manifest)

        # Step 4 — Invalidate CloudFront so the new content is live
        invalidate_cloudfront([
            "/data/videos.json",
            "/api/videos",
            "/api/latest",
            f"/videos/{video_id}*",
        ])

        print(f"Successfully published video {video_id} to https://{DOMAIN}")
        return {
            "statusCode": 200,
            "body": json.dumps({
                "video_id": video_id,
                "message": "published successfully",
                "total_published": len(published_videos),
                "website": f"https://{DOMAIN}",
            }),
        }

    except Exception as e:
        print(f"ERROR publishing video {video_id}: {e}")
        update_video_status(video_id, "publish_error", extra={
            "error_message": str(e)[:500],
        })
        raise
