"""
Video Processor Lambda
======================
Invoked asynchronously by the Video Downloader.

Workflow:
  1. Receive video_id, job_id, raw_s3_key from the downloader.
  2. Fetch source video description via YouTube Data API v3.
  3. Use Bedrock text model to rewrite the narrative in Keith Floyd's voice
     and generate scene descriptions matching the original video.
  4. Start 5 parallel async Bedrock Nova Reel jobs (5 * 6s = 30s).
  5. Generate Keith Floyd narration audio via Amazon Polly.
  6. Poll until all Bedrock jobs complete.
  7. Download all clips + audio, concatenate with ffmpeg, merge audio.
  8. Upload the final 30-second video to the processed-videos bucket.
  9. Update DynamoDB records and invoke the Website Publisher.

Amazon Nova Reel (amazon.nova-reel-v1:0) generates 6-second silent clips.
We generate 5 clips with scene prompts derived from the original video content
and stitch them together with LLM-generated Polly narration that follows
the source video's narrative in Keith Floyd's voice.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
import boto3
import requests
from datetime import datetime, timezone

s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime")
polly = boto3.client("polly")
dynamodb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")
secrets_client = boto3.client("secretsmanager")

RAW_BUCKET = os.environ["RAW_VIDEOS_BUCKET"]
PROCESSED_BUCKET = os.environ["PROCESSED_VIDEOS_BUCKET"]
VIDEOS_TABLE = os.environ["VIDEOS_TABLE_NAME"]
JOBS_TABLE = os.environ["JOBS_TABLE_NAME"]
CONTENT_TABLE = os.environ["CONTENT_TABLE_NAME"]
MODEL_ID = os.environ["BEDROCK_MODEL_ID"]
PROMPT = os.environ["KEITH_FLOYD_PROMPT"]
PUBLISHER_FN = os.environ["WEBSITE_PUBLISHER_FUNCTION"]
YOUTUBE_API_KEY_SECRET = os.environ.get("YOUTUBE_API_KEY_SECRET", "")

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

# Bedrock text model for analysing source video and generating Floyd narration
TEXT_MODEL_ID = "amazon.nova-lite-v1:0"

# Fallback scenes if LLM generation fails
FALLBACK_SCENES = [
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


def build_clip_prompt(title: str, scene_idx: int, scenes: list[str]) -> str:
    """
    Construct the prompt for a single Nova Reel clip.
    Each clip gets a different scene variation. Must stay under 512 chars.
    """
    base = PROMPT.strip()
    scene = scenes[scene_idx % len(scenes)]
    full = f'{base} Scene: {scene}. Food review "{title}".'

    if len(full) > 512:
        full = full[:509] + "..."

    print(f"  Clip {scene_idx + 1} prompt ({len(full)} chars): {full[:80]}...")
    return full


# -- Source Video Analysis ---------------------------------------------------

def get_youtube_api_key() -> str:
    """Retrieve YouTube API key from Secrets Manager."""
    if not YOUTUBE_API_KEY_SECRET:
        raise ValueError("YOUTUBE_API_KEY_SECRET env var not set")
    secret = secrets_client.get_secret_value(SecretId=YOUTUBE_API_KEY_SECRET)
    return secret["SecretString"]


def fetch_video_details(video_id: str) -> dict:
    """
    Fetch video description and tags from YouTube Data API v3.
    Returns dict with 'description' and 'tags'.
    """
    try:
        api_key = get_youtube_api_key()
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet",
            "id": video_id,
            "key": api_key,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not data.get("items"):
            print(f"No YouTube data found for {video_id}")
            return {"description": "", "tags": []}

        snippet = data["items"][0]["snippet"]
        desc = snippet.get("description", "")
        tags = snippet.get("tags", [])
        print(f"Fetched YouTube details for {video_id}: {len(desc)} char description, {len(tags)} tags")
        return {"description": desc, "tags": tags}

    except Exception as e:
        print(f"WARNING: Could not fetch YouTube details for {video_id}: {e}")
        return {"description": "", "tags": []}


def generate_content_with_llm(title: str, description: str, tags: list[str]) -> dict:
    """
    Use Bedrock text model to generate:
      1. A Keith Floyd narration that follows the original video's narrative.
      2. Five scene descriptions matching the original video content.

    Returns dict with 'narration' (str) and 'scenes' (list of 5 strings).
    """
    context = f'Video title: "{title}"'
    if description:
        context += f"\n\nOriginal video description:\n{description[:2000]}"
    if tags:
        context += f"\n\nVideo tags: {', '.join(tags[:20])}"

    prompt = (
        "You are rewriting a YouTube food review video's narration in the voice of "
        "Keith Floyd, the famous 1980s British TV chef known for his charm, wit, "
        "and love of wine. He is always holding a glass of red wine.\n\n"
        f"{context}\n\n"
        "Generate TWO things:\n\n"
        "1. NARRATION: Write a narration that covers the SAME topics, places, dishes, "
        "and opinions as the original video but delivered in Keith Floyd's charming, "
        "witty speaking style. Keep the facts and narrative from the original. "
        "About 30 seconds of speech (75-90 words). Plain text only, no SSML tags.\n\n"
        "2. SCENES: Generate exactly 5 short visual scene descriptions for an AI video "
        "generator. Each scene should match what happens in the original video "
        "(entering the venue, looking at menus, examining food, tasting, reacting, etc). "
        "Each scene MUST include the person holding or having a glass of red wine. "
        "Each description must be under 80 characters.\n\n"
        "Format your response EXACTLY as:\n"
        "NARRATION:\n[narration text here]\n\n"
        "SCENES:\n1. [scene 1]\n2. [scene 2]\n3. [scene 3]\n4. [scene 4]\n5. [scene 5]"
    )

    print(f"Calling Bedrock text model ({TEXT_MODEL_ID}) for Floyd content...")
    response = bedrock.converse(
        modelId=TEXT_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 600, "temperature": 0.7},
    )

    result_text = response["output"]["message"]["content"][0]["text"]
    print(f"LLM response ({len(result_text)} chars):\n{result_text[:300]}...")
    return parse_llm_response(result_text)


def parse_llm_response(text: str) -> dict:
    """Parse the LLM response into narration and scenes."""
    narration = ""
    scenes = []

    if "NARRATION:" in text and "SCENES:" in text:
        narr_part = text.split("NARRATION:")[1].split("SCENES:")[0].strip()
        scenes_part = text.split("SCENES:")[1].strip()

        narration = narr_part

        for line in scenes_part.strip().split("\n"):
            line = line.strip()
            if line and line[0].isdigit():
                scene = re.sub(r'^\d+\.\s*', '', line).strip()
                if scene:
                    scenes.append(scene)

    # Fallback if parsing failed
    if not narration:
        narration = (
            f'Well hello darlings! What we have here is rather special. '
            f'It\'s "{title}" and I must say, absolutely marvellous. '
            f'Just look at those colours and textures! '
            f'With a glass of wine in hand, what more could you ask for? Cheers!'
        )
    if len(scenes) < 5:
        while len(scenes) < 5:
            scenes.append(FALLBACK_SCENES[len(scenes)])

    print(f"Parsed: {len(narration)} char narration, {len(scenes)} scenes")
    return {"narration": narration, "scenes": scenes[:5]}


def analyse_source_video(video_id: str, title: str) -> dict:
    """
    Analyse the source YouTube video and generate Keith Floyd content.
    Returns dict with 'narration' and 'scenes'.
    Falls back to generic content if analysis fails.
    """
    try:
        details = fetch_video_details(video_id)
        content = generate_content_with_llm(
            title, details["description"], details["tags"]
        )
        return content
    except Exception as e:
        print(f"WARNING: Source video analysis failed: {e}. Using fallback content.")
        return {
            "narration": (
                f'Well hello darlings! What we have here is rather special. '
                f'It\'s "{title}" and I must say, absolutely marvellous. '
                f'Just look at those colours and textures! '
                f'The flavour is rich, bold, and utterly divine. '
                f'With a nice glass of wine in hand, what more could you ask for? '
                f'Cheers, darlings!'
            ),
            "scenes": list(FALLBACK_SCENES),
        }


def generate_narration(narration_text: str, work_dir: str) -> str:
    """
    Generate Keith Floyd narration audio via Amazon Polly.
    Takes the LLM-generated narration text and converts to speech.
    Returns the path to the generated MP3 file.
    """
    # Escape text for SSML safety
    safe_text = narration_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ssml = f'<speak><prosody rate="95%">{safe_text}</prosody></speak>'
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


def start_all_clips(video_id: str, title: str, scenes: list[str]) -> list[dict]:
    """
    Start all 5 Bedrock Nova Reel jobs with retry/backoff.
    Returns a list of {clip_idx, invocation_arn, output_prefix}.
    """
    jobs = []
    for i in range(NUM_CLIPS):
        output_prefix = f"bedrock-output/{video_id}/clip-{i}/"
        output_s3_uri = f"s3://{PROCESSED_BUCKET}/{output_prefix}"
        prompt_text = build_clip_prompt(title, i, scenes)

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

    1. Analyse source YouTube video (description, tags).
    2. Use Bedrock text model to generate Floyd narration + scene descriptions.
    3. Start 5 parallel Bedrock Nova Reel jobs (5 x 6s clips).
    4. Generate Polly narration audio concurrently.
    5. Download all clips, concatenate with ffmpeg, merge audio.
    6. Upload final 30s video and trigger publisher.

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

        # Step 2 -- Analyse source video and generate Floyd content
        print("Analysing source YouTube video...")
        content = analyse_source_video(video_id, title)
        print(f"Generated narration ({len(content['narration'])} chars) and {len(content['scenes'])} scenes")

        # Step 3 -- Start all Bedrock clips in parallel with dynamic scenes
        print(f"Starting {NUM_CLIPS} Bedrock Nova Reel jobs...")
        clip_jobs = start_all_clips(video_id, title, content["scenes"])
        update_job_status(job_id, "bedrock_running", extra={
            "num_clips": NUM_CLIPS,
        })

        # Step 4 -- Generate Polly narration while Bedrock runs
        work_dir = tempfile.mkdtemp(prefix="floyd-")
        audio_path = generate_narration(content["narration"], work_dir)

        # Step 5 -- Poll until all clips complete
        print("Polling Bedrock jobs...")
        poll_all_clips(clip_jobs)

        # Step 6 -- Download all clips
        print("Downloading clips from S3...")
        clip_paths = []
        for job in sorted(clip_jobs, key=lambda j: j["clip_idx"]):
            path = download_clip(job, work_dir)
            clip_paths.append(path)

        # Step 7 -- Concatenate clips and merge audio
        output_path = concatenate_and_merge(clip_paths, audio_path, work_dir)

        # Step 8 -- Upload final video
        processed_key = upload_final_video(video_id, output_path)
        update_job_status(job_id, "completed", extra={
            "processed_s3_key": processed_key,
            "duration_seconds": TOTAL_DURATION,
        })

        # Step 9 -- Update video record and save content entry
        update_video_status(video_id, "processed", extra={
            "processed_s3_key": processed_key,
            "processed_bucket": PROCESSED_BUCKET,
            "duration_seconds": TOTAL_DURATION,
        })
        save_content_record(video_id, processed_key, title)

        # Step 10 -- Trigger website publishing
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
