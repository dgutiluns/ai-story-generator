#!/usr/bin/env python3
import os, json, tempfile, subprocess, uuid, shutil
from flask import Flask, request, jsonify, send_file
import requests
from gtts import gTTS
from werkzeug.utils import secure_filename
import os, uuid
from urllib.parse import quote_plus
import requests
from flask import Flask, request, jsonify


app = Flask(__name__)

POLLINATIONS_TEXT = "https://text.pollinations.ai/openai"
POLLINATIONS_IMAGE = "https://image.pollinations.ai/prompt/"
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.getcwd(), "data"))
FRAMES_DIR = os.path.join(DATA_DIR, "frames")
AUDIO_DIR  = os.path.join(DATA_DIR, "audio")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")

# Add to your Python service's environment
DEEPGRAM_API_KEY= "597f05b9700111d51840862064280f8582369689"


for d in [DATA_DIR, FRAMES_DIR, AUDIO_DIR, OUTPUT_DIR]:
    os.makedirs(d, exist_ok=True)

def pollinations_chat(messages, model="openai", temperature=0.6, json_mode=False):
    payload = {"model": model,"messages": messages,"temperature": temperature}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(POLLINATIONS_TEXT, json=payload, timeout=120)
    r.raise_for_status()
    try:
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return content
    except Exception:
        return r.text

@app.post("/script")
def make_script():
    body = request.get_json(force=True)
    story = body.get("story", {})
    inventor = story.get("inventor", "Unknown Inventor")
    invention = story.get("invention", "Unknown Invention")
    hook = story.get("hook", "")
    summary = story.get("summary", "")
    
    sys = {"role": "system","content": (
        "You are a scriptwriter for 60-second short-form videos. "
        "Write a script under 150 words, split into 5-7 scenes with timestamps that total <= 60 seconds. "
        "Return STRICT JSON with keys: title, full_narration, scenes. "
        "scenes is an array of {scene_index, start, end, narration, prompt}. "
        "The prompt must describe the exact image that should appear in that scene. "
        "Avoid camera jargon; be concrete about subjects, setting, era, lighting, composition."
    )}
    usr = {"role": "user","content": (
        f"Create a <=60s script about {inventor} and the creation of {invention}. "
        f"Hook: {hook}. Summary for context: {summary}. "
        "Ensure scenes cover: origin moment, key challenge, breakthrough, impact. "
        "Timestamps should be monotonic starting at 0.0."
    )}
    content = pollinations_chat([sys, usr], model="openai", temperature=0.5, json_mode=True)
    try:
        data = json.loads(content)
    except Exception:
        data = {"title": f"{inventor} and the {invention}","full_narration": content[:800],"scenes": []}
    return jsonify(data)

@app.post("/storyboard")
def refine_storyboard():
    body = request.get_json(force=True)
    script = body.get("script", {})
    scenes = script.get("scenes", [])
    
    sys = {
        "role": "system",
        "content": (
            "You are a senior image prompt engineer for historical, cinematic visuals.\n"
            "Rewrite EACH scene's `prompt` into ONE richly detailed, single-shot prompt that would generate a realistic, "
            "period-accurate frame matching the narration. MAX 800 characters per prompt. DO NOT add camera jargon like 'bokeh' "
            "unless justified; be concrete and visual. Keep it ONE sentence, no lists.\n\n"
            "For every scene, the prompt MUST include:\n"
            " • Era & location cues (year/decade, country/city/setting)\n"
            " • Subject (who/what), pose/action, facial expression\n"
            " • Wardrobe & props authentic to period\n"
            " • Environment & foreground/background set dressing\n"
            " • Lighting (type + direction), time of day, weather if relevant\n"
            " • Composition (shot type and angle) e.g., 'tight medium shot at desk, eye-level', 'wide establishing from doorway'\n"
            " • Color palette/mood (e.g., 'muted, smoky ambers and brass')\n\n"
            "Return STRICT JSON only:\n"
            "{ \"scenes\": [ { \"scene_index\": <int>, \"start\": <number>, \"end\": <number>,\n"
            "  \"narration\": <string>, \"prompt\": <string> } ] }\n"
            "Rules:\n"
            " • Keep scene_index as supplied (if it starts at 0, keep it; if 1, keep it).\n"
            " • Do not invent new scenes or change timings.\n"
            " • PROMPT MUST BE <= 480 chars and one sentence.\n"
            " • No markdown, no labels, JSON only."
        )
    }
    
    usr = {"role": "user","content": json.dumps({"scenes": scenes})}
    content = pollinations_chat([sys, usr], model="openai", temperature=0.6, json_mode=True)
    try:
        refined = json.loads(content)
        script["scenes"] = refined.get("scenes", scenes)
    except Exception:
        pass
    return jsonify(script)


@app.post("/frame")
def upload_frame():
    if "file" not in request.files:
        return jsonify({"error": "missing file"}), 400
    f = request.files["file"]
    name = request.form.get("name", f"frame_{uuid.uuid4().hex}.jpg")
    name = secure_filename(name)
    out_path = os.path.join(FRAMES_DIR, name)
    f.save(out_path)
    return jsonify({"saved": out_path})




@app.post("/tts")
def tts():
    data = request.get_json()
    text = data.get("text", "").strip()
    voice = data.get("voice", "aura-asteria-en")
    filename = f"narration_{uuid.uuid4().hex}.mp3"
    save_path = os.path.join(AUDIO_DIR, filename)

    # Debug info
    debug_info = {
        "input_length": len(text),
        "deepgram_status": None,
        "key_used": "597f05..."  # Shortened for logs
    }

    # Try Deepgram with exact curl-compatible format
    try:
        print("Sending to Deepgram with text:", text[:50] + "...")  # Log first 50 chars
        
        response = requests.post(
            "https://api.deepgram.com/v1/speak?model=" + voice,  # Model in URL
            headers={
                "Authorization": "Token 597f05b9700111d51840862064280f8582369689",
                "Content-Type": "application/json"
            },
            json={"text": text[:1000]},  # Simpler payload
            timeout=10
        )
        
        debug_info["deepgram_status"] = response.status_code
        debug_info["response_sample"] = response.text[:200] if response.text else None

        if response.status_code == 200:
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return {
                "path": save_path,
                "engine": "deepgram",
                "debug": debug_info
            }
        else:
            print(f"Deepgram failed. Status: {response.status_code}, Response: {response.text[:200]}")
            
    except Exception as e:
        debug_info["error"] = str(e)
        print(f"Deepgram exception: {str(e)}")

    # Fallback to gTTS
    try:
        tts = gTTS(text=text, lang='en')
        tts.save(save_path)
        return {
            "path": save_path,
            "engine": "gTTS",
            "debug": debug_info
        }
    except Exception as e:
        return {"error": str(e), "debug": debug_info}, 500


@app.post("/save-audio")
def save_audio():
    # Get file and path from request
    audio_file = request.files.get('file')
    custom_path = request.form.get('path', '')
    
    if not audio_file:
        return {"error": "No file provided"}, 400

    # Generate filename
    filename = secure_filename(audio_file.filename or f"audio_{uuid.uuid4().hex}.mp3")
    save_path = os.path.join(AUDIO_DIR, custom_path, filename)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    # Save file
    try:
        audio_file.save(save_path)
        return {"success": True, "path": save_path}
    except Exception as e:
        return {"error": str(e)}, 500


@app.post("/assemble")
def assemble():
    body = request.get_json(force=True) or {}
    
    # Extract and validate core parameters
    frames_dir = body.get("framesDir", FRAMES_DIR)
    audio_path = body.get("audioPath", "")
    scene_durations = body.get("sceneDurations", [])
    frame_paths = body.get("framePaths", [])
    fps = 30  # Fixed frame rate for slideshow

    # Validate required inputs
    if not os.path.isdir(frames_dir):
        return jsonify({"error": f"framesDir not found: {frames_dir}"}), 400
    if not os.path.isfile(audio_path):
        return jsonify({"error": f"audioPath not found: {audio_path}"}), 400

    # Get frame files (use provided paths or scan directory)
    if frame_paths:
        images = [p for p in frame_paths if os.path.exists(p)]
    else:
        try:
            images = sorted(
                [os.path.join(frames_dir, f) 
                 for f in os.listdir(frames_dir) 
                 if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
            )
        except Exception as e:
            return jsonify({"error": f"Could not list frames: {str(e)}"}), 500

    if not images:
        return jsonify({"error": "No valid images found"}), 400

    # Calculate durations if not provided
    if not scene_durations:
        script = body.get("script", {}).get("scenes", [])
        if script and len(script) == len(images):
            scene_durations = [
                (script[i+1]["start"] if i+1 < len(script) else script[i]["end"]) - scene["start"]
                for i, scene in enumerate(script)
            ]
        else:
            # Fallback: equal durations totaling 60 seconds
            scene_durations = [60/len(images)] * len(images)

    # Create temp working directory
    temp_dir = tempfile.mkdtemp(prefix="video_assembly_")
    output_path = body.get("outputPath", os.path.join(OUTPUT_DIR, "final_video.mp4"))

    try:
        # 1) Create individual frame videos with precise durations
        frame_videos = []
        for idx, (img_path, duration) in enumerate(zip(images, scene_durations)):
            frame_video = os.path.join(temp_dir, f"frame_{idx:04d}.mp4")
            
            run_cmd([
                "ffmpeg", "-y",
                "-loop", "1",              # Loop single image
                "-i", img_path,            # Input image
                "-c:v", "libx264",         # Video codec
                "-t", str(duration),       # Exact duration
                "-vf", "scale=1080:-2",    # Scale to 1080p height
                "-pix_fmt", "yuv420p",     # Pixel format
                "-r", str(fps),            # Frame rate
                frame_video                # Output
            ], f"render_frame_{idx}")
            frame_videos.append(frame_video)

        # 2) Concatenate all frame videos
        concat_list = os.path.join(temp_dir, "concat.txt")
        with open(concat_list, "w") as f:
            f.write("\n".join(f"file '{os.path.basename(f)}'" for f in frame_videos))

        intermediate_video = os.path.join(temp_dir, "intermediate.mp4")
        run_cmd([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",          # Stream copy (no re-encode)
            intermediate_video
        ], "concatenate_frames")

        # 3) Mix with audio (with proper duration handling)
        run_cmd([
            "ffmpeg", "-y",
            "-i", intermediate_video,
            "-i", audio_path,
            "-c:v", "copy",         # Keep video as-is
            "-c:a", "aac",          # Encode audio
            "-map", "0:v",          # Use video from first input
            "-map", "1:a",          # Use audio from second input
            "-shortest",            # End when shortest stream ends
            output_path
        ], "mix_audio")

        # Verify output
        if not os.path.exists(output_path):
            raise RuntimeError("Final video file was not created")

        return jsonify({
            "success": True,
            "output": output_path,
            "duration": sum(scene_durations),
            "frameCount": len(images)
        })

    except Exception as e:
        app.logger.error("Video assembly failed: %s", str(e))
        return jsonify({
            "error": str(e),
            "body": {k:v for k,v in body.items() if k != "script"}  # Don't dump full script
        }), 500

    finally:
        # Cleanup temp files
        shutil.rmtree(temp_dir, ignore_errors=True)

def run_cmd(cmd, step_name):
    """Helper to run shell commands with proper logging"""
    app.logger.info("[%s] Executing: %s", step_name, " ".join(cmd))
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    if result.returncode != 0:
        error_msg = f"{step_name} failed (exit {result.returncode})"
        app.logger.error("%s\nCommand: %s\nStderr: %s", 
                        error_msg, " ".join(cmd), result.stderr)
        raise RuntimeError(error_msg)
    
    return result

@app.get("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)
