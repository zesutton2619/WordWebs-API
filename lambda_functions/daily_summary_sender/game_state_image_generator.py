"""
Game state image generation for daily summaries
Python port of the frontend gameStateImage.js with Discord avatar integration
"""

import io
import requests
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Optional, Any


class GameStateImageGenerator:
    """Generate game state images matching the frontend styling"""
    
    def __init__(self):
        # WordWebs difficulty colors (matching gameStateImage.js)
        self.colors = {
            1: "#16a34a",  # Green (Level 1)
            2: "#ca8a04",  # Yellow (Level 2) 
            3: "#ea580c",  # Orange (Level 3)
            4: "#dc2626",  # Red (Level 4)
            "wrong": "#64748b",  # Gray for wrong guesses
            "empty": "#374151",  # Dark gray for empty slots
            "background": "#0f172a",  # Dark slate background
            "white": "#ffffff",
            "light_gray": "#cbd5e1",
            "border": "#1e293b"
        }
        
        # Canvas settings (matching gameStateImage.js)
        self.canvas_width = 250
        self.canvas_height = 225  # Slightly taller to accommodate avatar
        
    def generate_player_summary_image(
        self,
        player_data: Dict[str, Any],
        puzzle_number: int,
        date: str
    ) -> bytes:
        """
        Generate a daily summary image for a single player
        
        Args:
            player_data: Dict containing player info and game state
            puzzle_number: The puzzle number
            date: The date string
            
        Returns:
            bytes: PNG image data
        """
        
        # Create image
        img = Image.new('RGB', (self.canvas_width, self.canvas_height), self.colors["background"])
        draw = ImageDraw.Draw(img)
        
        # Try to load fonts (fallback to default if not available)
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
            header_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
            status_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except:
            # Fallback to default font
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            status_font = ImageFont.load_default()
        
        current_y = 10
        
        # Add Discord avatar if available
        avatar_size = 25
        if player_data.get('avatar_url'):
            try:
                avatar_img = self._download_and_resize_avatar(player_data['avatar_url'], avatar_size)
                if avatar_img:
                    # Position avatar in top-left
                    avatar_x = 10
                    avatar_y = current_y
                    img.paste(avatar_img, (avatar_x, avatar_y))
            except Exception as e:
                print(f"Failed to add avatar: {e}")
        
        # Add title text (offset if avatar present)
        title_x = self.canvas_width // 2
        title_y = current_y + 15
        draw.text((title_x, title_y), f"Word Webs #{puzzle_number}", 
                 fill=self.colors["white"], font=title_font, anchor="mt")
        
        # Add player name
        player_name = player_data.get('display_name', 'Player')
        name_y = title_y + 17
        draw.text((title_x, name_y), player_name, 
                 fill=self.colors["light_gray"], font=header_font, anchor="mt")
        
        current_y = name_y + 17
        
        # Game state visualization
        solved_groups = player_data.get('solved_groups', [])
        guesses = player_data.get('guesses', [])
        attempts_remaining = player_data.get('attempts_remaining', 0)
        
        # Draw solved groups as horizontal bars (matching gameStateImage.js)
        current_y = self._draw_solved_groups(draw, solved_groups, current_y)
        
        # Draw remaining words grid
        current_y = self._draw_remaining_words_grid(draw, solved_groups, current_y)
        
        # Add attempt dots (matching gameStateImage.js)
        if len(solved_groups) < 4:
            current_y = self._draw_attempt_dots(draw, attempts_remaining, current_y)
        
        # Add completion status
        status_text, status_color = self._get_status_text(solved_groups, guesses)
        status_y = current_y + 12
        draw.text((self.canvas_width // 2, status_y), status_text,
                 fill=status_color, font=status_font, anchor="mt")
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        return img_bytes.getvalue()
    
    def _download_and_resize_avatar(self, avatar_url: str, size: int) -> Optional[Image.Image]:
        """Download and resize Discord avatar"""
        try:
            response = requests.get(avatar_url, timeout=5)
            response.raise_for_status()
            
            avatar = Image.open(io.BytesIO(response.content))
            avatar = avatar.convert('RGBA')
            
            # Resize to square
            avatar = avatar.resize((size, size), Image.Resampling.LANCZOS)
            
            # Create circular mask
            mask = Image.new('L', (size, size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, size, size), fill=255)
            
            # Apply circular mask
            avatar.putalpha(mask)
            
            return avatar
            
        except Exception as e:
            print(f"Error downloading avatar: {e}")
            return None
    
    def _draw_solved_groups(self, draw: ImageDraw.Draw, solved_groups: List[Dict], start_y: int) -> int:
        """Draw solved groups as colored horizontal bars"""
        if not solved_groups:
            return start_y
            
        row_height = 22
        row_padding = 4
        
        # Calculate grid dimensions (matching gameStateImage.js)
        grid_size = 20
        grid_padding = 3
        words_per_row = 4
        grid_width = words_per_row * grid_size + (words_per_row - 1) * grid_padding
        grid_start_x = (self.canvas_width - grid_width) // 2
        
        current_y = start_y
        
        # Sort by difficulty (matching gameStateImage.js)
        sorted_groups = sorted(solved_groups, key=lambda x: x.get('difficulty', 1))
        
        for group in sorted_groups:
            difficulty = group.get('difficulty', 1)
            color = self.colors.get(difficulty, self.colors[1])
            
            # Draw rounded rectangle
            self._draw_rounded_rect(draw, grid_start_x, current_y, grid_width, row_height, 4, color)
            current_y += row_height + row_padding
            
        return current_y
    
    def _draw_remaining_words_grid(self, draw: ImageDraw.Draw, solved_groups: List[Dict], start_y: int) -> int:
        """Draw remaining words as a grid of gray boxes"""
        total_words = 16
        solved_words = len(solved_groups) * 4
        remaining_words = total_words - solved_words
        
        if remaining_words <= 0:
            return start_y
            
        current_y = start_y + 2  # Small spacing
        
        # Grid settings (matching gameStateImage.js)
        grid_size = 20
        grid_padding = 3
        words_per_row = 4
        grid_start_x = (self.canvas_width - (words_per_row * grid_size + (words_per_row - 1) * grid_padding)) // 2
        
        rows = (remaining_words + words_per_row - 1) // words_per_row
        
        # Draw grid of remaining words
        for i in range(remaining_words):
            row = i // words_per_row
            col = i % words_per_row
            x = grid_start_x + col * (grid_size + grid_padding)
            y = current_y + row * (grid_size + grid_padding)
            
            # Draw empty box
            self._draw_rounded_rect(draw, x, y, grid_size, grid_size, 3, self.colors["empty"])
            
            # Add border
            self._draw_rounded_rect_outline(draw, x, y, grid_size, grid_size, 3, self.colors["border"], 0.75)
        
        return current_y + rows * (grid_size + grid_padding) + 10
    
    def _draw_attempt_dots(self, draw: ImageDraw.Draw, attempts_remaining: int, start_y: int) -> int:
        """Draw attempt dots (matching gameStateImage.js)"""
        dot_size = 4
        dot_spacing = 8
        total_dots = 4
        
        dots_width = (total_dots - 1) * dot_spacing + dot_size
        dots_start_x = (self.canvas_width - dots_width) // 2
        dots_y = start_y + 15
        
        for i in range(total_dots):
            dot_x = dots_start_x + i * dot_spacing
            
            # White dot for remaining attempts, gray for used
            color = self.colors["white"] if i < attempts_remaining else self.colors["wrong"]
            
            draw.ellipse(
                [dot_x, dots_y, dot_x + dot_size, dots_y + dot_size],
                fill=color
            )
        
        return dots_y + dot_size + 5
    
    def _get_status_text(self, solved_groups: List[Dict], guesses: List) -> tuple:
        """Get status text and color (matching gameStateImage.js logic)"""
        if len(solved_groups) == 4:
            return "Completed!", "#22c55e"
        elif len(guesses) >= 4 and len(solved_groups) < 4:
            return "Failed", "#ef4444"
        else:
            return f"{len(solved_groups)}/4 groups found", self.colors["light_gray"]
    
    def _draw_rounded_rect(self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int, radius: int, color: str):
        """Draw a rounded rectangle"""
        draw.rounded_rectangle([x, y, x + width, y + height], radius=radius, fill=color)
    
    def _draw_rounded_rect_outline(self, draw: ImageDraw.Draw, x: int, y: int, width: int, height: int, radius: int, color: str, width_px: float):
        """Draw a rounded rectangle outline"""
        draw.rounded_rectangle([x, y, x + width, y + height], radius=radius, outline=color, width=int(width_px))


def generate_combined_summary_image(players_data: List[Dict[str, Any]], puzzle_number: int, date: str) -> bytes:
    """
    Generate a combined summary image showing multiple players
    
    Args:
        players_data: List of player data dictionaries
        puzzle_number: The puzzle number
        date: The date string
        
    Returns:
        bytes: PNG image data
    """
    generator = GameStateImageGenerator()
    
    # For now, generate individual images and combine them vertically
    # This is a simplified version - you could make it more sophisticated
    
    if not players_data:
        # Return empty state image
        img = Image.new('RGB', (250, 100), generator.colors["background"])
        draw = ImageDraw.Draw(img)
        draw.text((125, 50), "No completed games today", 
                 fill=generator.colors["light_gray"], anchor="mm")
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        return img_bytes.getvalue()
    
    # For multiple players, create a grid layout
    max_players_to_show = 6  # Limit to prevent huge images
    players_to_show = players_data[:max_players_to_show]
    
    # Create individual player images
    player_images = []
    for player in players_to_show:
        try:
            img_bytes = generator.generate_player_summary_image(player, puzzle_number, date)
            player_images.append(Image.open(io.BytesIO(img_bytes)))
        except Exception as e:
            print(f"Failed to generate image for player {player.get('display_name', 'unknown')}: {e}")
    
    if not player_images:
        # Fallback to text-only image
        img = Image.new('RGB', (250, 100), generator.colors["background"])
        draw = ImageDraw.Draw(img)
        draw.text((125, 50), f"Word Webs #{puzzle_number} - {len(players_data)} players completed", 
                 fill=generator.colors["white"], anchor="mm")
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        return img_bytes.getvalue()
    
    # Arrange images in a grid (3 players per row, dynamic width)
    cols = min(3, len(player_images))  # Max 3 columns, but fewer if less players
    rows = (len(player_images) + cols - 1) // cols
    
    img_width = player_images[0].width
    img_height = player_images[0].height
    
    # Dynamic width based on number of players (max 3 per row)
    combined_width = cols * img_width
    combined_height = rows * img_height
    
    combined_img = Image.new('RGB', (combined_width, combined_height), generator.colors["background"])
    
    for i, player_img in enumerate(player_images):
        row = i // cols
        col = i % cols
        x = col * img_width
        y = row * img_height
        combined_img.paste(player_img, (x, y))
    
    # Convert to bytes
    img_bytes = io.BytesIO()
    combined_img.save(img_bytes, format='PNG')
    return img_bytes.getvalue()