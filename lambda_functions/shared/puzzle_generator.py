import openai
import json
import re
import os
import random
from typing import Dict, List, Any

class PuzzleGenerator:
    def __init__(self):
        self.client = openai.OpenAI(
            api_key=os.environ['GEMINI_API_KEY'],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
    
    def generate_puzzle(self, theme: str = None, max_retries: int = 3) -> Dict[str, Any]:
        """Generate a new puzzle with optional theme"""
        for attempt in range(max_retries):
            try:
                puzzle = self._call_gemini_api(theme)
                if self._validate_puzzle(puzzle):
                    return self._format_puzzle(puzzle)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                continue
        
        raise Exception("Failed to generate valid puzzle after maximum retries")
    
    def _call_gemini_api(self, theme: str = None) -> Dict[str, Any]:
        """Call Gemini API via OpenAI-compatible interface"""
        theme_prompt = f" related to {theme}" if theme else ""
        
        prompt = f"""Create a word puzzle game like NYT Connections{theme_prompt}. Generate exactly 16 words that form 4 groups of 4 words each.

Rules:
- Each group should have a clear connection/category, but make it tricky like NYT Connections
- Words should be single words only (no phrases, no proper nouns)
- Difficulty levels: 1 (easiest/most obvious), 2 (medium), 3 (harder), 4 (hardest/most deceptive)
- Groups should have varied difficulty levels (one of each: 1, 2, 3, 4)
- IMPORTANT: Include words that could seemingly belong to multiple categories to create red herrings
- Difficulty 4 should have an unexpected or clever connection that's not immediately obvious
- Some words should be deliberately misleading - they look like they go with one group but actually belong to another
- Make players second-guess their choices, especially for harder difficulties

Examples of good misdirection:
- A word that could be both a verb and a noun
- Words that sound like they belong to an obvious category but actually share a more subtle connection
- Mix literal and figurative meanings

Return ONLY a valid JSON object in this exact format:
{{
  "groups": [
    {{"words": ["WORD1", "WORD2", "WORD3", "WORD4"], "category": "CATEGORY NAME", "difficulty": 1}},
    {{"words": ["WORD5", "WORD6", "WORD7", "WORD8"], "category": "CATEGORY NAME", "difficulty": 2}},
    {{"words": ["WORD9", "WORD10", "WORD11", "WORD12"], "category": "CATEGORY NAME", "difficulty": 3}},
    {{"words": ["WORD13", "WORD14", "WORD15", "WORD16"], "category": "CATEGORY NAME", "difficulty": 4}}
  ]
}}"""

        response = self.client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            reasoning_effort="none"
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group()
        
        return json.loads(response_text)
    
    def _validate_puzzle(self, puzzle_data: Dict[str, Any]) -> bool:
        """Validate puzzle structure and content"""
        if "groups" not in puzzle_data:
            return False
        
        groups = puzzle_data["groups"]
        if len(groups) != 4:
            return False
        
        all_words = []
        difficulties = []
        
        for group in groups:
            if not all(key in group for key in ["words", "category", "difficulty"]):
                return False
            
            if len(group["words"]) != 4:
                return False
            
            # Check for single words (no spaces)
            for word in group["words"]:
                if " " in word.strip():
                    return False
            
            all_words.extend([word.upper().strip() for word in group["words"]])
            difficulties.append(group["difficulty"])
        
        # Check total word count
        if len(all_words) != 16:
            return False
        
        # Check for duplicate words
        if len(set(all_words)) != 16:
            return False
        
        # Check difficulty levels are 1-4
        if not all(1 <= d <= 4 for d in difficulties):
            return False
        
        return True
    
    def _format_puzzle(self, puzzle_data: Dict[str, Any]) -> Dict[str, Any]:
        """Format puzzle for database storage"""
        all_words = []
        formatted_groups = []
        
        for group in puzzle_data["groups"]:
            words_upper = [word.upper().strip() for word in group["words"]]
            all_words.extend(words_upper)
            
            formatted_groups.append({
                "words": words_upper,
                "category": group["category"].strip(),
                "difficulty": group["difficulty"]
            })
        
        # Shuffle words for presentation
        random.shuffle(all_words)
        
        return {
            "words": all_words,
            "groups": formatted_groups
        }