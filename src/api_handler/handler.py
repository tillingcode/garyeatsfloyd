"""
API Handler Lambda
==================
Serves the GaryEatsFloyd REST API via API Gateway.

Endpoints:
  GET /api/health           — Health check
  GET /api/videos           — List all published videos (newest first)
  GET /api/videos/{videoId} — Get a single video by ID
  GET /api/latest           — Get the most recently published video
"""

import json
import os
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")

VIDEOS_TABLE = os.environ["VIDEOS_TABLE_NAME"]
CONTENT_TABLE = os.environ["CONTENT_TABLE_NAME"]
PROCESSED_BUCKET = os.environ["PROCESSED_VIDEOS_BUCKET"]
CF_DOMAIN = os.environ["CLOUDFRONT_DOMAIN"]


# ── Helpers ────────────────────────────────────────────────────────────────────

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o) if o % 1 else int(o)
        return super().default(o)


def respond(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": f"https://{CF_DOMAIN}",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def format_video(item: dict) -> dict:
    """Format a DynamoDB video item for the API response."""
    video_id = item.get("video_id", "")
    return {
        "video_id": video_id,
        "title": item.get("title", "Untitled"),
        "description": item.get("summary", ""),
        "thumbnail": f"https://{CF_DOMAIN}/thumbnails/{video_id}.jpg",
        "video_url": f"https://{CF_DOMAIN}/videos/{video_id}.mp4",
        "status": item.get("status", "unknown"),
        "published_at": item.get("published_at", ""),
        "original_channel": item.get("author", "@GaryEats"),
        "original_url": item.get("original_url", ""),
        "duration_seconds": item.get("duration_seconds", 0),
    }


def get_published_videos(limit: int = 50) -> list[dict]:
    """Query the status-published-index GSI for published videos."""
    table = dynamodb.Table(VIDEOS_TABLE)
    response = table.query(
        IndexName="status-published-index",
        KeyConditionExpression=Key("status").eq("published"),
        ScanIndexForward=False,  # newest first
        Limit=limit,
    )
    return [format_video(item) for item in response.get("Items", [])]


def get_all_videos(limit: int = 50) -> list[dict]:
    """Scan for all videos (including processing/error states)."""
    table = dynamodb.Table(VIDEOS_TABLE)
    response = table.scan(Limit=limit)
    items = response.get("Items", [])
    # Sort by published_at descending
    items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return [format_video(item) for item in items]


def get_video_by_id(video_id: str) -> dict | None:
    """Get a single video by its ID."""
    table = dynamodb.Table(VIDEOS_TABLE)
    response = table.get_item(Key={"video_id": video_id})
    item = response.get("Item")
    return format_video(item) if item else None


def get_latest_video() -> dict | None:
    """Get the most recently published video."""
    videos = get_published_videos(limit=1)
    return videos[0] if videos else None


# ── Handler ────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """Route API Gateway requests to the appropriate handler."""
    path = event.get("rawPath", "/")
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    query = event.get("queryStringParameters") or {}

    print(f"API request: {method} {path}")

    # Handle CORS preflight
    if method == "OPTIONS":
        return respond(200, {})

    # ── Health check ──
    if path == "/api/health":
        return respond(200, {
            "status": "ok",
            "service": "GaryEatsFloyd API",
            "timestamp": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        })

    # ── List videos ──
    if path == "/api/videos":
        status_filter = query.get("status", "published")
        limit = min(int(query.get("limit", "50")), 100)

        if status_filter == "all":
            videos = get_all_videos(limit=limit)
        else:
            videos = get_published_videos(limit=limit)

        return respond(200, {
            "videos": videos,
            "total": len(videos),
        })

    # ── Latest video ──
    if path == "/api/latest":
        video = get_latest_video()
        if video:
            return respond(200, {"video": video})
        return respond(200, {"video": None, "message": "No published videos yet"})

    # ── Single video ──
    if path.startswith("/api/videos/"):
        video_id = path.split("/")[-1]
        if not video_id:
            return respond(400, {"error": "video_id required"})

        video = get_video_by_id(video_id)
        if video:
            return respond(200, {"video": video})
        return respond(404, {"error": f"Video {video_id} not found"})

    # ── 404 ──
    return respond(404, {"error": "not found", "path": path})
