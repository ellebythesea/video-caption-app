import openai
import os
import subprocess
import tempfile
from typing import Optional
import re

from config import (
    OPENAI_API_KEY,
    TRIM_SILENCE,
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_BITRATE,
    CAPTION_SPLIT_THRESHOLD,
)
from logger import log_message
from news import get_latest_news_summary


def _get_ffmpeg_path() -> str:
    """Return a usable ffmpeg executable path.

    Prefers the imageio-ffmpeg bundled binary when available, otherwise falls
    back to the system's `ffmpeg` in PATH.
    """
    try:
        import imageio_ffmpeg  # type: ignore

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

def _format_caption_for_readability(text: str) -> str:
    """Ensure reasonable line breaks and hashtag placement.

    - Normalizes line endings.
    - If no line breaks are present, inserts a newline after sentence endings.
    - Moves trailing hashtag block to its own final line, separated by a blank line.
    """
    try:
        s = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()

        # Detect trailing hashtag block (one or more hashtags near the end)
        tag_block = None
        m = re.search(r"(\s*(?:#[\w\d_]+)(?:\s*#[\w\d_]+)+)\s*$", s)
        if m:
            tag_block = m.group(1)
            s = s[: m.start()].rstrip()

        # Normalize excessive blank lines
        s = re.sub(r"\n{3,}", "\n\n", s).strip()

        # Build up to two paragraphs from existing breaks or by splitting sentences
        paragraphs: list[str] = []
        if "\n\n" in s:
            parts = s.split("\n\n")
            # Clean inner single linebreaks inside each paragraph
            parts = [" ".join(p.strip().splitlines()) for p in parts]
            if len(parts) <= 2:
                paragraphs = parts
            else:
                # Keep first as is; merge the rest into second
                paragraphs = [parts[0], " ".join(parts[1:]).strip()]
        else:
            # No explicit paragraphs; split into sentences and form 1–2 paragraphs
            sentences = re.split(r'(?<=[.!?…][)\]\}"\'”’]?)\s+', s)
            sentences = [seg.strip() for seg in sentences if seg.strip()]
            base_body = " ".join(sentences)
            if len(sentences) <= 2:
                # If short, keep one paragraph. If long, force two when possible.
                if len(base_body) > CAPTION_SPLIT_THRESHOLD and len(sentences) >= 2:
                    paragraphs = [sentences[0], " ".join(sentences[1:]).strip()]
                elif len(base_body) > CAPTION_SPLIT_THRESHOLD and len(sentences) == 1:
                    # Heuristic split: prefer last comma/semicolon near 40–60% region
                    n = len(base_body)
                    lo = int(n * 0.35)
                    hi = int(n * 0.65)
                    cut = -1
                    for i in range(hi, lo, -1):
                        if base_body[i-1] in ",;:" and i < n - 10:
                            cut = i
                            break
                    if cut == -1:
                        # Fallback: nearest space to midpoint
                        mid = n // 2
                        left = base_body.rfind(" ", 0, mid)
                        right = base_body.find(" ", mid)
                        if left == -1 and right == -1:
                            paragraphs = [base_body]
                        else:
                            if left == -1:
                                cut = right
                            elif right == -1:
                                cut = left
                            else:
                                cut = left if (mid - left) <= (right - mid) else right
                    if cut != -1:
                        p1 = base_body[:cut].strip()
                        p2 = base_body[cut:].strip()
                        paragraphs = [p1, p2] if p2 else [p1]
                    else:
                        paragraphs = [base_body]
                else:
                    paragraphs = [base_body]
            else:
                total_len = sum(len(x) for x in sentences)
                target = max(total_len // 2, 1)
                acc = []
                acc_len = 0
                for i, sent in enumerate(sentences):
                    acc.append(sent)
                    acc_len += len(sent)
                    # Ensure at least one sentence remains for paragraph 2
                    if acc_len >= target and i < len(sentences) - 1:
                        break
                p1 = " ".join(acc).strip()
                p2 = " ".join(sentences[len(acc):]).strip()
                if p2:
                    paragraphs = [p1, p2]
                else:
                    paragraphs = [p1]

        body = "\n\n".join([p for p in paragraphs if p])

        # Rebuild with hashtags block, ensuring separation
        if tag_block:
            # Normalize spaces within tags line and dedupe while preserving order
            tags = re.findall(r"#[\w\d_]+", tag_block)
            seen = set()
            deduped = []
            for t in tags:
                if t not in seen:
                    seen.add(t)
                    deduped.append(t)
            tags_line = " ".join(deduped).strip()
            if tags_line:
                return f"{body}\n\n{tags_line}" if body else tags_line
        return body
    except Exception:
        # Fail open: return original text if formatting fails
        return text


def apply_chatgpt_prompt(transcript, prompt="", news_context=""):
    try:
        # Cleaned prompt structure: all guidance in the system message; user carries only context and transcript
        SYS_PROMPT = (
            "You are a sharp political analyst. Rewrite the transcript into a short, clear social post "
            "under 1300 characters using exactly 2 simple paragraphs. The first paragraph must be the "
            "most important summary in 250 characters or fewer, and it must include all hashtags. Use "
            "3 to 5 relevant hashtags total, prioritizing the main people the post is about, then a "
            "single-word subject hashtag that helps discovery in trending news, then any remaining "
            "relevant tags. The second paragraph should add a bit more context with verified facts, "
            "dates, and numbers when relevant. Include direct transcript quotes where available. Verify "
            "names and quotes carefully. Any hashtag that appears in the caption body counts toward the "
            "same total of 3 to 5 hashtags. Avoid speculation, flourish, links, or Trump’s current "
            "office status."
        )
        # Optionally allow an extra hint without polluting the user message
        if prompt:
            SYS_PROMPT = SYS_PROMPT + " Additional instructions: " + str(prompt).strip()
        if not news_context or news_context.startswith("LATEST NEWS CONTEXT:\nNo recent news") or news_context.startswith("LATEST NEWS CONTEXT:\nUnable"):
            news_context = "LATEST NEWS CONTEXT:\nNo external news context available. Focus solely on the transcript for analysis.\n\n"
        user_content = f"{news_context}\n\nTRANSCRIPT:\n{transcript}"
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=500,
            temperature=0.35,
        )
        text = response.choices[0].message.content.strip()

        # Post-process to avoid phrases like "Former President Trump"
        def sanitize_caption(s: str) -> str:
            # Replace variants with "President Trump" and preserve possessive
            def repl_president(m):
                suffix = m.group(1) or ""
                return "President Trump" + suffix

            patterns = [
                r"(?i)\bformer\s+(?:u\.?s\.?\s+)?president\s+(?:donald\s+(?:j\.?\s+)?trump|trump)(’s|'s)?",
                r"(?i)\bex[-\s]?president\s+(?:donald\s+(?:j\.?\s+)?trump|trump)(’s|'s)?",
            ]
            for pat in patterns:
                s = re.sub(pat, repl_president, s)
            return s

        formatted = _format_caption_for_readability(sanitize_caption(text))
        return formatted
    except Exception as e:
        log_message(f"Error with ChatGPT API: {str(e)}")
        return f"Error processing with ChatGPT: {str(e)}"

def process_caption(transcript, prompt=""):
    news_context = get_latest_news_summary(transcript)
    return apply_chatgpt_prompt(transcript, prompt, news_context)
