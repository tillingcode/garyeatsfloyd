"""
Video Processor Lambda
======================
Invoked asynchronously by the Video Downloader.

Workflow:
  1. Receive video_id, job_id, raw_s3_key from the downloader.
  2. Start an async Bedrock Nova Reel video generation job using the
     raw video as input and the Keith Floyd prompt.
  3. Poll / wait for the Bedrock job to complete (Nova Reel is async).
  4. Download the generated video from the Bedrock output S3 location.
  5. Upload the processed video to the processed-videos bucket.
  6. Update DynamoDB records and invoke the Website Publisher.

Amazon Nova Reel (amazon.nova-reel-v1:0) uses the
StartAsyncInvoke API for video generation.
"""

import json
import os
import time
import uuid
import boto3
from datetime import datetime, timezone

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

RAW_BUCKET = os.environ["RAW_VIDEOS_BUCKET"]
PROCESSED_BUCKET = os.environ["PROCESSED_VIDEOS_BUCKET"]
VIDEOS_TABLE = os.environ["VIDEOS_TABLE_NAME"]
JOBS_TABLE = os.environ["JOBS_TABLE_NAME"]
CONTENT_TABLE = os.environ["CONTENT_TABLE_NAME"]
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
PROMPT = os.environ["KEITH_FLOYD_PROMPT"]
PUBLISHER_FN = os.environ["WEBSITE_PUBLISHER_FUNCTION"]

# Bedrock async job polling
MAX_WAIT_SECONDS = 780  # 13 minutes (leave buffer within 15-min Lambda timeout)
POLL_INTERVAL = 30


# ── Helpers ────────────────────────────────────────────────────────────────────

def update_job_status(job_id: str, status: str, extra: dict | None = None):
    """Update processing job record in DynamoDB."""
    table = dynamodb.Table(JOBS_TABLE)
    update_expr = "SET job_status = :s, updated_at = :now"
    expr_values = {":s": status, ":now": datetime.now(timezone.utc).isoformat()}

    if extra:
        for k, v in extra.items():
            update_expr += f", {k} = :{k}"
            expr_values[f":{k}"] = v

    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )


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


def build_floyd_prompt(title: str) -> str:
    """
    Construct the full prompt for Nova Reel. Must stay under 512 characters
    (Nova Reel TEXT_VIDEO hard limit).
    """
    # Build a compact prompt that captures the Keith Floyd essence
    base = PROMPT.strip()
    video_context = f' Cooking show: "{title}". Man holds red wine glass, mentions wine, tipsy charm.'
    full = base + video_context

    # Hard truncate at 512 chars to stay within Nova Reel limit
    if len(full) > 512:
        full = full[:509] + "..."

    print(f"Prompt length: {len(full)} chars")
    return full


def start_bedrock_job(video_id: str, raw_s3_key: str, title: str) -> str:
    """
    Start an async Nova Reel video generation job.
    Returns the Bedrock invocation ARN for polling.
    """
    output_s3_uri = f"s3://{PROCESSED_BUCKET}/bedrock-output/{video_id}/"
    input_s3_uri = f"s3://{RAW_BUCKET}/{raw_s3_key}"
    prompt_text = build_floyd_prompt(title)

    print(f"Starting Bedrock async invocation:")
    print(f"  Model: {MODEL_ID}")
    print(f"  Input: {input_s3_uri}")
    print(f"  Output: {output_s3_uri}")

    model_input = {
        "taskType": "TEXT_VIDEO",
        "textToVideoParams": {
            "text": prompt_text,
        },
        "videoGenerationConfig": {
            "durationSeconds": 6,
            "fps": 24,
            "dimension": "1280x720",
        },
    }

    response = bedrock.start_async_invoke(
        modelId=MODEL_ID,
        modelInput=model_input,
        outputDataConfig={
            "s3OutputDataConfig": {
                "s3Uri": output_s3_uri,
            }
        },
    )

    invocation_arn = response["invocationArn"]
    print(f"Bedrock job started: {invocation_arn}")
    return invocation_arn


def poll_bedrock_job(invocation_arn: str) -> dict:
    """
    Poll the Bedrock async invocation until it completes or times out.
    Returns the final response with status and output location.
    """
    elapsed = 0
    while elapsed < MAX_WAIT_SECONDS:
        response = bedrock.get_async_invoke(invocationArn=invocation_arn)
        status = response.get("status", "Unknown")
        print(f"  Bedrock job status: {status} (elapsed: {elapsed}s)")

        if status == "Completed":
            return response
        elif status in ("Failed", "Cancelled"):
            failure_msg = response.get("failureMessage", "Unknown error")
            raise RuntimeError(f"Bedrock job failed: {failure_msg}")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise TimeoutError(f"Bedrock job did not complete within {MAX_WAIT_SECONDS}s")


def copy_processed_video(video_id: str, bedrock_output: dict) -> str:
    """
    Copy the Bedrock-generated video from the output location to a clean
    key in the processed-videos bucket. Returns the final S3 key.
    """
    # Nova Reel outputs to the specified S3 prefix
    output_prefix = f"bedrock-output/{video_id}/"

    # List objects at the output prefix to find the generated video
    response = s3.list_objects_v2(Bucket=PROCESSED_BUCKET, Prefix=output_prefix)
    video_files = [
        obj["Key"] for obj in response.get("Contents", [])
        if obj["Key"].endswith((".mp4", ".webm", ".mkv"))
    ]

    if not video_files:
        raise FileNotFoundError(f"No video file found at s3://{PROCESSED_BUCKET}/{output_prefix}")

    source_key = video_files[0]
    ext = os.path.splitext(source_key)[1] or ".mp4"
    final_key = f"videos/{video_id}{ext}"

    print(f"Copying {source_key} → {final_key}")
    s3.copy_object(
        Bucket=PROCESSED_BUCKET,
        CopySource={"Bucket": PROCESSED_BUCKET, "Key": source_key},
        Key=final_key,
        ContentType="video/mp4",
    )

    return final_key


def save_content_record(video_id: str, processed_key: str, title: str):
    """Write a website content record for the processed video."""
    table = dynamodb.Table(CONTENT_TABLE)
    now = datetime.now(timezone.utc).isoformat()

    table.put_item(Item={
        "content_id": video_id,
        "content_type": "processed_video",
        "title": title,
        "s3_key": processed_key,
        "s3_bucket": PROCESSED_BUCKET,
        "video_url": f"/videos/{video_id}.mp4",
        "created_at": now,
        "updated_at": now,
    })


def invoke_publisher(video_id: str, processed_key: str, title: str):
    """Asynchronously invoke the Website Publisher Lambda."""
    payload = {
        "video_id": video_id,
        "processed_s3_key": processed_key,
        "title": title,
    }
    print(f"Invoking website publisher for {video_id}")
    lambda_client.invoke(
        FunctionName=PUBLISHER_FN,
        InvocationType="Event",
        Payload=json.dumps(payload).encode(),
    )


# ── Handler ────────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """
    Process a raw video through Bedrock Nova Reel, transforming it into
    the Keith Floyd style with wine references throughout.

    Expected event: { video_id, job_id, raw_s3_key, raw_bucket, title }
    """
    video_id = event["video_id"]
    job_id = event["job_id"]
    raw_s3_key = event["raw_s3_key"]
    title = event.get("title", "Untitled")

    print(f"Video Processor invoked: {video_id} — {title}")
    print(f"Job: {job_id}, Source: s3://{RAW_BUCKET}/{raw_s3_key}")

    try:
        # Step 1 — Update status to processing
        update_video_status(video_id, "processing")
        update_job_status(job_id, "processing")

        # Step 2 — Start Bedrock async video generation
        invocation_arn = start_bedrock_job(video_id, raw_s3_key, title)
        update_job_status(job_id, "bedrock_running", extra={
            "bedrock_invocation_arn": invocation_arn,
        })

        # Step 3 — Poll until complete
        bedrock_result = poll_bedrock_job(invocation_arn)

        # Step 4 — Copy generated video to final location
        processed_key = copy_processed_video(video_id, bedrock_result)
        update_job_status(job_id, "completed", extra={
            "processed_s3_key": processed_key,
        })

        # Step 5 — Update video record and save content entry
        update_video_status(video_id, "processed", extra={
            "processed_s3_key": processed_key,
            "processed_bucket": PROCESSED_BUCKET,
        })
        save_content_record(video_id, processed_key, title)

        # Step 6 — Trigger website publishing
        invoke_publisher(video_id, processed_key, title)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "video_id": video_id,
                "job_id": job_id,
                "processed_key": processed_key,
                "message": "processing complete, publishing triggered",
            }),
        }

    except Exception as e:
        error_msg = str(e)[:500]
        print(f"ERROR processing video {video_id}: {e}")
        update_video_status(video_id, "processing_error", extra={"error_message": error_msg})
        update_job_status(job_id, "failed", extra={"error_message": error_msg})
        raise
