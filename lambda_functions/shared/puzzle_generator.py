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
    
    def get_previous_puzzle_examples(self, db_client) -> List[Dict[str, Any]]:
        """Get the most recent puzzle's groups to use as examples to avoid"""
        try:
            from datetime import datetime, timedelta
            
            # Try yesterday first, then day before, etc.
            for i in range(1, 8):  # Check up to 7 days back
                date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                puzzle = db_client.get_daily_puzzle(date)
                if puzzle and puzzle.get('groups'):
                    return puzzle['groups']
            
            return []
        except:
            return []
    
    def generate_puzzle(self, theme: str = None, max_retries: int = 3, db_client=None) -> Dict[str, Any]:
        """Generate a new puzzle with optional theme and dynamic prompt"""
        for attempt in range(max_retries):
            try:
                puzzle = self._call_gemini_api(theme, db_client)
                if self._validate_puzzle(puzzle):
                    return self._format_puzzle(puzzle)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                continue
        
        raise Exception("Failed to generate valid puzzle after maximum retries")
    
    def _call_gemini_api(self, theme: str = None, db_client=None) -> Dict[str, Any]:
        """Call Gemini API via OpenAI-compatible interface with dynamic prompt"""
        theme_prompt = f" with a focus on {theme}" if theme else ""
        
        # Get previous puzzle's groups to use as examples to avoid
        previous_groups = []
        if db_client:
            previous_groups = self.get_previous_puzzle_examples(db_client)
        
        # Build dynamic avoid section
        avoid_section = ""
        if previous_groups:
            avoid_section = f"""
CRITICAL - DO NOT REPEAT THESE CATEGORY TYPES FROM THE PREVIOUS PUZZLE:
"""
            for group in previous_groups:
                avoid_section += f"- Difficulty {group['difficulty']}: \"{group['category']}\" (words: {', '.join(group['words'])})\n"
            
            avoid_section += """
You must create COMPLETELY DIFFERENT types of connections for each difficulty level."""
        
        prompt = f"""Create a NYT Connections-style word puzzle{theme_prompt}. Generate exactly 16 words that form 4 groups of 4 words each.

CRITICAL: You must create MAXIMUM CONFUSION between categories. Players should struggle to figure out which words go together.

DIFFICULTY GUIDELINES:
- Difficulty 1: Obvious connection that most people see immediately
- Difficulty 2: Clear connection once you think about it, but not the first thing noticed  
- Difficulty 3: Requires lateral thinking; connection isn't immediately apparent
- Difficulty 4: Clever, unexpected connection that makes people say "Oh wow!" when revealed

DIFFICULTY 4 CREATIVITY RULE:
Create a connection that's clever but not obvious. This could be:
- Wordplay or linguistic tricks
- Unexpected shared properties  
- Hidden patterns or relationships
- Creative categorization
BE CREATIVE AND ORIGINAL - don't repeat the same type of difficulty 4 connection!

{avoid_section}

MANDATORY RED HERRING REQUIREMENTS:
- At least 8 words must reasonably fit into 2+ different categories
- Create "decoy groups" that seem obvious but are wrong
- Include words that are near-misses for other categories

AVOID THESE MISTAKES:
- Don't put obvious categories in high difficulty slots
- Don't repeat the same type of difficulty 4 connection
- Difficulty 4 should be clever and surprising, not just obscure
- Ensure proper difficulty progression from easy to mind-bending

You MUST create confusion and misdirection. Each puzzle should have multiple words that genuinely seem to belong in different categories.

Return ONLY valid JSON in this exact format:
{{
  "groups": [
    {{"words": ["WORD1", "WORD2", "WORD3", "WORD4"], "category": "CATEGORY NAME", "difficulty": 1}},
    {{"words": ["WORD5", "WORD6", "WORD7", "WORD8"], "category": "CATEGORY NAME", "difficulty": 2}},
    {{"words": ["WORD9", "WORD10", "WORD11", "WORD12"], "category": "CATEGORY NAME", "difficulty": 3}},
    {{"words": ["WORD13", "WORD14", "WORD15", "WORD16"], "category": "CATEGORY NAME", "difficulty": 4}}
  ]
}}"""

        response = self.client.chat.completions.create(
            model="gemini-2.5-pro",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group()
        
        return json.loads(response_text)
    
    def _validate_puzzle(self, puzzle_data: Dict[str, Any]) -> bool:
        """Enhanced validation with quality checks"""
        if "groups" not in puzzle_data:
            return False
        
        groups = puzzle_data["groups"]
        if len(groups) != 4:
            return False
        
        all_words = []
        difficulties = []
        categories = []
        
        for group in groups:
            if not all(key in group for key in ["words", "category", "difficulty"]):
                return False
            
            if len(group["words"]) != 4:
                return False
            
            # Check for single words (no spaces, hyphens, or proper nouns)
            for word in group["words"]:
                word_clean = word.strip()
                if " " in word_clean or "-" in word_clean:
                    return False
                # Basic proper noun check (starts with capital and has lowercase)
                if word_clean[0].isupper() and any(c.islower() for c in word_clean[1:]):
                    return False
            
            all_words.extend([word.upper().strip() for word in group["words"]])
            difficulties.append(group["difficulty"])
            categories.append(group["category"].strip())
        
        # Check total word count
        if len(all_words) != 16:
            return False
        
        # Check for duplicate words
        if len(set(all_words)) != 16:
            return False
        
        # Check difficulty levels are 1-4 and unique
        if sorted(difficulties) != [1, 2, 3, 4]:
            return False
        
        # Check for duplicate categories
        if len(set(categories)) != 4:
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