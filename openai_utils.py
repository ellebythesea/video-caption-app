import openai
import os
import subprocess
import tempfile
from typing import Optional

from config import OPENAI_API_KEY, TRIM_SILENCE, AUDIO_SAMPLE_RATE, AUDIO_CHANNELS, AUDIO_BITRATE
from logger import log_message
from news import get_latest_news_summary


def _get_ffmpeg_path() -> str:
    """Return a usable ffmpeg executable path.

    Prefers the imageio-ffmpeg bundled binary when available, otherwise falls
    back to the system's `ffmpeg` in PATH.
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _extract_downsampled_audio(input_path: str, trim_silence: bool = TRIM_SILENCE) -> Optional[str]:
    """Extract mono 16kHz audio at low bitrate, optionally trimming silence.

    Returns the path to a temporary .wav file, or None on failure.
    """
    try:
        ffmpeg = _get_ffmpeg_path()
        # Create a temp wav file for the output
        tmp_fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(tmp_fd)  # ffmpeg will write to this path

        # Build ffmpeg command
        cmd = [
            ffmpeg,
            "-y",  # overwrite output
            "-i",
            input_path,
            "-vn",  # drop video
            "-ac",
            str(AUDIO_CHANNELS),
            "-ar",
            str(AUDIO_SAMPLE_RATE),
            "-b:a",
            str(AUDIO_BITRATE),
        ]

        # Optional silence trimming (conservative thresholds)
        if trim_silence:
            # Trim near-silence at start/end; keep mid-speech pauses
            af = (
                "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-40dB:"
                "stop_periods=1:stop_duration=0.8:stop_threshold=-40dB"
            )
            cmd.extend(["-af", af])

        cmd.append(out_path)

        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            log_message(
                f"ffmpeg audio extract failed (rc={proc.returncode}): {proc.stderr.decode(errors='ignore')[:500]}"
            )
            try:
                os.unlink(out_path)
            except Exception:
                pass
            return None

        return out_path
    except FileNotFoundError:
        # ffmpeg not found
        log_message("ffmpeg not found; sending original file to Whisper.")
        return None
    except Exception as e:
        log_message(f"Audio preprocessing error: {e}")
        return None

client = openai.OpenAI(api_key=OPENAI_API_KEY)

def transcribe_video(video_path):
    try:
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        # Extract and compress audio first for faster uploads/processing
        processed = _extract_downsampled_audio(video_path)
        src_path = processed or video_path
        with open(src_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file)
        return transcript.text
    except Exception as e:
        log_message(f"Error transcribing video: {str(e)}")
        return None
    finally:
        # Cleanup temp file if we created one
        try:
            if 'processed' in locals() and processed and os.path.exists(processed):
                os.unlink(processed)
        except Exception:
            pass

def apply_chatgpt_prompt(transcript, prompt="", news_context=""):
    try:
        if not prompt:
            prompt = """
            You are a sharp political analyst. Analyze the transcript and news context with concise, factual insights, focusing on voter dynamics, political moves, and geopolitical impacts. Start with the main individual’s name and key findings. Use specific examples, names, or events, adding context and details to statements, and avoid vague or invented details. Verify names and quote individuals accurately where possible based on the transcript.
            Rewrite text into a short social post under 1300 characters. Use 1–2 simple paragraphs, adding verified facts, dates, and numbers to expand the transcript. Include direct quotes from the transcript where available. Include #hashtags for trending terms once (e.g., #Election2025), not at name ends. End with an 8–13 hashtag paragraph, no links or sources. Do not mention Trump’s current office status or include summaries at the end.
            """
        if not news_context or news_context.startswith("LATEST NEWS CONTEXT:\nNo recent news") or news_context.startswith("LATEST NEWS CONTEXT:\nUnable"):
            news_context = "LATEST NEWS CONTEXT:\nNo external news context available. Focus solely on the transcript for analysis.\n\n"
        full_prompt = f"{news_context}TRANSCRIPT:\n{transcript}\n\nTASK:\n{prompt}"
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a sharp political analyst. Rewrite the transcript into a short social post under 1300 characters. Use 1–2 simple paragraphs, adding verified facts, dates, and numbers to expand statements. Include direct quotes from the transcript where available and verify names and quotes against the transcript. End with an 8–13 hashtag paragraph. Avoid flourish, speculation, or Trump’s office status."},
                {"role": "user", "content": full_prompt}
            ],
            max_tokens=500,
            temperature=0.5
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log_message(f"Error with ChatGPT API: {str(e)}")
        return f"Error processing with ChatGPT: {str(e)}"

def process_caption(transcript, prompt=""):
    news_context = get_latest_news_summary(transcript)
    return apply_chatgpt_prompt(transcript, prompt, news_context)
