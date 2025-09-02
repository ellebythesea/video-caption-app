# openai_utils.py
import openai
from config import OPENAI_API_KEY
from logger import log_message
from news import get_latest_news_summary

openai.api_key = OPENAI_API_KEY

def transcribe_video(video_path):
    try:
        with open(video_path, "rb") as audio_file:
            transcript = openai.Audio.transcribe("whisper-1", audio_file)
        return transcript['text']
    except Exception as e:
        log_message(f"Error transcribing video: {str(e)}")
        return None

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
        response = openai.ChatCompletion.create(
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