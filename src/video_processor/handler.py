"""
Video Processor Lambda
======================
Invoked asynchronously by the Video Downloader.

Workflow:
  1. Receive video_id, job_id, raw_s3_key from the downloader.
  2. Start 5 parallel async Bedrock Nova Reel jobs (5 × 6s = 30s).
  3. Generate Keith Floyd narration audio via Amazon Polly.
  4. Poll until all Bedrock jobs complete.
  5. Download all clips + audio, concatenate with ffmpeg, merge audio.
  6. Upload the final 30-second video to the processed-videos bucket.
  7. Update DynamoDB records and invoke the Website Publisher.

Amazon Nova Reel (amazon.nova-reel-v1:0) generates 6-second silent clips.
We generate 5 clips with varied scene prompts and stitch them together
with Polly-generated narration for a 30-second video with audio.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import boto3
from datetime import datetime, timezone

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
polly = boto3.client("polly")
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
NUM_CLIPS = 5
CLIP_DURATION = 6  # seconds per Nova Reel clip
TOTAL_DURATION = NUM_CLIPS * CLIP_DURATION  # 30 seconds
MAX_WAIT_SECONDS = 780  # 13 minutes (leave buffer within 15-min Lambda timeout)
POLL_INTERVAL = 30

# ffmpeg binary -- copy from layer to /tmp and make executable (zip from Windows
# doesn't preserve Unix execute permissions)
_FFMPEG_LAYER_PATH = "/opt/bin/ffmpeg"
_FFMPEG_TMP_PATH = "/tmp/ffmpeg"


def _ensure_ffmpeg() -> str:
    """Ensure ffmpeg binary is available and executable in /tmp."""
    if os.path.exists(_FFMPEG_TMP_PATH) and os.access(_FFMPEG_TMP_PATH, os.X_OK):
        return _FFMPEG_TMP_PATH
    shutil.copy2(_FFMPEG_LAYER_PATH, _FFMPEG_TMP_PATH)
    os.chmod(_FFMPEG_TMP_PATH, os.stat(_FFMPEG_TMP_PATH).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"ffmpeg ready at {_FFMPEG_TMP_PATH}")
    return _FFMPEG_TMP_PATH

# Scene variations for each clip to create visual progression
SCENE_TEMPLATES = [
    "walks into a bustling restaurant, looks around, holding wine glass, warm lighting",
    "sits at table, examines a plated dish closely, holds wine glass, animated gestures",
    "takes a bite of food, reacts with delight, wine glass in hand, restaurant setting",
    "chats to camera about the dish, gestures at food on plate, wine glass nearby",
    "gives a thumbs up, raises wine glass, smiles at camera, restaurant background",
]


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


def build_clip_prompt(title: str, scene_idx: int) -> str:
    """
    Construct the prompt for a single Nova Reel clip.
    Each clip gets a different scene variation. Must stay under 512 chars.
    """
    base = PROMPT.strip()
    scene = SCENE_TEMPLATES[scene_idx % len(SCENE_TEMPLATES)]
    full = f'{base} Scene: {scene}. Food review "{title}".'

    if len(full) > 512:
        full = full[:509] + "..."

    print(f"  Clip {scene_idx + 1} prompt ({len(full)} chars): {full[:80]}...")
    return full


def build_narration_script(title: str) -> str:
    """
    Generate a Keith Floyd-style narration script for Polly.
    About 30 seconds of speech at a natural pace.
    """
    return (
        f'<speak>'
        f'<prosody rate="95%">'
        f'Well, hello there darlings! '
        f'<break time="300ms"/>'
        f'Now, what we have here is rather special. '
        f'It\'s "{title}" and I must say, '
        f'<break time="200ms"/>'
        f'this is the sort of place that gets me excited. '
        f'<break time="300ms"/>'
        f'Just look at the presentation! '
        f'The textures, the colours, absolutely gorgeous. '
        f'<break time="200ms"/>'
        f'I mean, you can tell straight away '
        f'that someone in that kitchen knows what they\'re doing. '
        f'<break time="500ms"/>'
        f'Oh, and the flavour! '
        f'Rich, bold, and utterly divine. '
        f'<break time="300ms"/>'
        f'You know, the best food is the kind that makes you stop talking '
        f'and just enjoy the moment. '
        f'<break time="200ms"/>'
        f'And with a nice glass of wine in hand, '
        f'what more could you possibly ask for? '
        f'<break time="400ms"/>'
        f'Absolutely brilliant. Go and try it yourselves. '
        f'Cheers, darlings!'
        f'</prosody>'
        f'</speak>'
    )


def generate_narration(title: str, work_dir: str) -> str:
    """
    Generate Keith Floyd narration audio via Amazon Polly.
    Returns the path to the generated MP3 file.
    """
    ssml = build_narration_script(title)
    print(f"Generating Polly narration ({len(ssml)} chars SSML)")

    response = polly.synthesize_speech(
        Engine="neural",
        OutputFormat="mp3",
        SampleRate="24000",
        Text=ssml,
        TextType="ssml",
        VoiceId="Arthur",  # British English male voice
    )

    audio_path = os.path.join(work_dir, "narration.mp3")
    with open(audio_path, "wb") as f:
        f.write(response["AudioStream"].read())

    file_size = os.path.getsize(audio_path)
    print(f"Narration audio saved: {audio_path} ({file_size} bytes)")
    return audio_path


def start_all_clips(video_id: str, title: str) -> list[dict]:
    """
    Start all 5 Bedrock Nova Reel jobs with retry/backoff.
    Returns a list of {clip_idx, invocation_arn, output_prefix}.
    """
    jobs = []
    for i in range(NUM_CLIPS):
        output_prefix = f"bedrock-output/{video_id}/clip-{i}/"
        output_s3_uri = f"s3://{PROCESSED_BUCKET}/{output_prefix}"
        prompt_text = build_clip_prompt(title, i)

        model_input = {
            "taskType": "TEXT_VIDEO",
            "textToVideoParams": {
                "text": prompt_text,
            },
            "videoGenerationConfig": {
                "durationSeconds": CLIP_DURATION,
                "fps": 24,
                "dimension": "1280x720",
            },
        }

        # Retry with exponential backoff for throttling
        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = bedrock.start_async_invoke(
                    modelId=MODEL_ID,
                    modelInput=model_input,
                    outputDataConfig={
                        "s3OutputDataConfig": {
                            "s3Uri": output_s3_uri,
                        }
                    },
                )
                break
            except Exception as e:
                if attempt < max_retries - 1 and ("ServiceUnavailable" in str(e) or "Throttl" in str(e)):
                    wait = (2 ** attempt) * 5  # 5, 10, 20, 40, 80 seconds
                    print(f"  Clip {i + 1} attempt {attempt + 1} failed ({e}), retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        arn = response["invocationArn"]
        print(f"  Clip {i + 1}/{NUM_CLIPS} started: {arn}")
        jobs.append({
            "clip_idx": i,
            "invocation_arn": arn,
            "output_prefix": output_prefix,
        })

        # Small delay between clip starts to avoid bursting
        if i < NUM_CLIPS - 1:
            time.sleep(2)

    return jobs


def poll_all_clips(jobs: list[dict]) -> list[dict]:
    """
    Poll all Bedrock jobs until they all complete or timeout.
    Returns the jobs list with 'status' and 'failure' fields added.
    """
    pending = set(range(len(jobs)))
    elapsed = 0

    while pending and elapsed < MAX_WAIT_SECONDS:
        for i in list(pending):
            response = bedrock.get_async_invoke(
                invocationArn=jobs[i]["invocation_arn"]
            )
            status = response.get("status", "Unknown")

            if status == "Completed":
                jobs[i]["status"] = "Completed"
                pending.discard(i)
                print(f"  Clip {i + 1} completed (elapsed: {elapsed}s)")
            elif status in ("Failed", "Cancelled"):
                failure = response.get("failureMessage", "Unknown error")
                jobs[i]["status"] = "Failed"
                jobs[i]["failure"] = failure
                pending.discard(i)
                print(f"  Clip {i + 1} FAILED: {failure}")

        if pending:
            remaining = [j + 1 for j in pending]
            print(f"  Waiting for clips {remaining} (elapsed: {elapsed}s)")
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

    if pending:
        for i in pending:
            jobs[i]["status"] = "Timeout"
        raise TimeoutError(
            f"Clips {[j + 1 for j in pending]} did not complete within {MAX_WAIT_SECONDS}s"
        )

    failed = [j for j in jobs if j["status"] == "Failed"]
    if failed:
        msgs = "; ".join(f"clip {j['clip_idx']+1}: {j.get('failure','?')}" for j in failed)
        raise RuntimeError(f"Bedrock clip failures: {msgs}")

    return jobs


def download_clip(job: dict, work_dir: str) -> str:
    """Download a completed Bedrock clip from S3 to local file."""
    prefix = job["output_prefix"]
    idx = job["clip_idx"]

    response = s3.list_objects_v2(Bucket=PROCESSED_BUCKET, Prefix=prefix)
    video_files = [
        obj["Key"] for obj in response.get("Contents", [])
        if obj["Key"].endswith((".mp4", ".webm", ".mkv"))
    ]

    if not video_files:
        raise FileNotFoundError(
            f"No video file at s3://{PROCESSED_BUCKET}/{prefix}"
        )

    s3_key = video_files[0]
    local_path = os.path.join(work_dir, f"clip-{idx}.mp4")
    s3.download_file(PROCESSED_BUCKET, s3_key, local_path)
    size = os.path.getsize(local_path)
    print(f"  Downloaded clip {idx + 1}: {s3_key} ({size} bytes)")
    return local_path


def concatenate_and_merge(clip_paths: list[str], audio_path: str,
                          work_dir: str) -> str:
    """
    Use ffmpeg to concatenate video clips and merge narration audio.
    Returns the path to the final output MP4.
    """
    ffmpeg = _ensure_ffmpeg()

    # Write the ffmpeg concat file list
    concat_file = os.path.join(work_dir, "clips.txt")
    with open(concat_file, "w") as f:
        for path in clip_paths:
            f.write(f"file '{path}'\n")

    # Step 1: Concatenate all video clips into a single silent video
    silent_video = os.path.join(work_dir, "silent.mp4")
    cmd_concat = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_file,
        "-c", "copy",
        silent_video,
    ]
    print(f"Concatenating {len(clip_paths)} clips...")
    result = subprocess.run(cmd_concat, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"ffmpeg concat stderr: {result.stderr[:500]}")
        raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:300]}")

    # Step 2: Merge narration audio with the concatenated video
    output_path = os.path.join(work_dir, "output.mp4")
    cmd_merge = [
        ffmpeg, "-y",
        "-i", silent_video,
        "-i", audio_path,
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    print("Merging audio with video...")
    result = subprocess.run(cmd_merge, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"ffmpeg merge stderr: {result.stderr[:500]}")
        raise RuntimeError(f"ffmpeg merge failed: {result.stderr[:300]}")

    size = os.path.getsize(output_path)
    print(f"Final video: {output_path} ({size} bytes)")
    return output_path


def upload_final_video(video_id: str, output_path: str) -> str:
    """Upload the final video to the processed-videos bucket."""
    final_key = f"videos/{video_id}.mp4"
    print(f"Uploading final video to s3://{PROCESSED_BUCKET}/{final_key}")
    s3.upload_file(
        output_path,
        PROCESSED_BUCKET,
        final_key,
        ExtraArgs={"ContentType": "video/mp4"},
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
        "duration_seconds": TOTAL_DURATION,
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
    Generate a 30-second Keith Floyd style video with narration audio.

    1. Start 5 parallel Bedrock Nova Reel jobs (5 x 6s clips).
    2. Generate Polly narration audio concurrently.
    3. Download all clips, concatenate with ffmpeg, merge audio.
    4. Upload final 30s video and trigger publisher.

    Expected event: { video_id, job_id, raw_s3_key, raw_bucket, title }
    """
    video_id = event["video_id"]
    job_id = event["job_id"]
    raw_s3_key = event["raw_s3_key"]
    title = event.get("title", "Untitled")

    print(f"Video Processor invoked: {video_id} -- {title}")
    print(f"Job: {job_id}, Generating {NUM_CLIPS} clips x {CLIP_DURATION}s = {TOTAL_DURATION}s video")

    try:
        # Step 1 -- Update status to processing
        update_video_status(video_id, "processing")
        update_job_status(job_id, "processing")

        # Step 2 -- Start all Bedrock clips in parallel
        print(f"Starting {NUM_CLIPS} Bedrock Nova Reel jobs...")
        clip_jobs = start_all_clips(video_id, title)
        update_job_status(job_id, "bedrock_running", extra={
            "num_clips": NUM_CLIPS,
        })

        # Step 3 -- Generate Polly narration while Bedrock runs
        work_dir = tempfile.mkdtemp(prefix="floyd-")
        audio_path = generate_narration(title, work_dir)

        # Step 4 -- Poll until all clips complete
        print("Polling Bedrock jobs...")
        poll_all_clips(clip_jobs)

        # Step 5 -- Download all clips
        print("Downloading clips from S3...")
        clip_paths = []
        for job in sorted(clip_jobs, key=lambda j: j["clip_idx"]):
            path = download_clip(job, work_dir)
            clip_paths.append(path)

        # Step 6 -- Concatenate clips and merge audio
        output_path = concatenate_and_merge(clip_paths, audio_path, work_dir)

        # Step 7 -- Upload final video
        processed_key = upload_final_video(video_id, output_path)
        update_job_status(job_id, "completed", extra={
            "processed_s3_key": processed_key,
            "duration_seconds": TOTAL_DURATION,
        })

        # Step 8 -- Update video record and save content entry
        update_video_status(video_id, "processed", extra={
            "processed_s3_key": processed_key,
            "processed_bucket": PROCESSED_BUCKET,
            "duration_seconds": TOTAL_DURATION,
        })
        save_content_record(video_id, processed_key, title)

        # Step 9 -- Trigger website publishing
        invoke_publisher(video_id, processed_key, title)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "video_id": video_id,
                "job_id": job_id,
                "processed_key": processed_key,
                "duration_seconds": TOTAL_DURATION,
                "message": "processing complete, publishing triggered",
            }),
        }

    except Exception as e:
        error_msg = str(e)[:500]
        print(f"ERROR processing video {video_id}: {e}")
        update_video_status(video_id, "processing_error", extra={"error_message": error_msg})
        update_job_status(job_id, "failed", extra={"error_message": error_msg})
        raise
