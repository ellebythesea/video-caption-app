import requests
from collections import Counter
from logger import log_message
from config import SERPER_API_KEY
import re

def get_latest_news_summary(transcript, num_results=5):
    try:
        words = re.findall(r'\b\w+\b', transcript)
        stopwords = set(['the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'])
        cleaned_words = [word.lower() for word in words if word.lower() not in stopwords]
        proper_nouns = [words[i] for i in range(len(words)) if words[i][0].isupper() and words[i].lower() not in stopwords and (i == 0 or not words[i-1].endswith('.'))]
        word_counts = Counter(cleaned_words)
        frequent_words = [word for word, count in word_counts.most_common(10) if len(word) > 3][:5]
        keywords = list(set(proper_nouns + frequent_words))
        if len(keywords) < 3: keywords.extend(['latest news', 'political strategy', 'geopolitics'])
        search_query = " ".join(keywords[:5]) + " latest news today"
        url = "https://google.serper.dev/search"
        headers = {'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'}
        payload = {"q": search_query, "num": num_results, "tbm": "nws"}
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        news_items = [f"• {item.get('title', '')} ({item.get('date', '')}): {item.get('snippet', '')}" for item in data.get('news', [])[:num_results]]
        return "LATEST NEWS CONTEXT:\n" + "\n".join(news_items) + "\n\n" if news_items else "LATEST NEWS CONTEXT:\nNo recent news found for the specified query.\n\n"
    except Exception as e:
        log_message(f"Error fetching news: {str(e)}")
        return "LATEST NEWS CONTEXT:\nUnable to fetch latest news at this time.\n\n"