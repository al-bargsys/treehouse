"""
OpenAI client utility for generating bird names and backstories.
"""
import os
import logging
from typing import Optional, Tuple
from openai import OpenAI

logger = logging.getLogger(__name__)

class OpenAIBirdNamer:
    """Handles OpenAI API calls for bird naming and backstory generation."""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenAI client.
        
        Args:
            api_key: OpenAI API key. If None, will try to get from OPENAI_API_KEY env var.
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        self.client = None
        self.enabled = bool(self.api_key)
        
        if self.enabled:
            try:
                self.client = OpenAI(api_key=self.api_key)
                logger.info("OpenAI client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.enabled = False
        else:
            logger.info("OpenAI integration disabled (no API key provided)")
    
    def generate_bird_name(self) -> Optional[str]:
        """
        Generate a whimsical but plausible human first name for a bird.
        
        Returns:
            The generated name, or None if generation fails or is disabled.
        """
        if not self.enabled or not self.client:
            return None
        
        prompt = """Generate a whimsical but plausible human first name for a bird.

The name should sound like a person's name that you might meet at a diner, not a celebrity or fantasy name.

Output just the name — one word, capitalized — nothing else."""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=20
            )
            
            name = response.choices[0].message.content.strip()
            # Clean up the name - remove any quotes, extra whitespace, etc.
            name = name.strip('"\' \n\t')
            # Capitalize first letter
            if name:
                name = name[0].upper() + name[1:].lower() if len(name) > 1 else name.upper()
            
            logger.info(f"Generated bird name: {name}")
            return name
        except Exception as e:
            logger.error(f"Error generating bird name: {e}")
            return None
    
    def generate_bird_backstory(self, bird_name: str) -> Optional[str]:
        """
        Generate a funny two-sentence backstory for a bird.
        
        Args:
            bird_name: The name of the bird to generate a backstory for.
            
        Returns:
            The generated backstory, or None if generation fails or is disabled.
        """
        if not self.enabled or not self.client:
            return None
        
        prompt = f"""Create a short, funny two-sentence nonsense backstory for a bird named {bird_name}.

Randomly choose one of the following tones:

• overly serious nature documentary,

• pompous academic paper,

• noir detective monologue, or

• sensational tabloid article.

Each backstory should:

Sound confident but be absurd or self-contradictory.

Include at least one oddly specific detail about the bird's habits, history, or attitude toward humans.

Feel self-contained and humorous even out of context.

Output only the two sentences, with no headings or meta text."""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.9,
                max_tokens=150
            )
            
            backstory = response.choices[0].message.content.strip()
            logger.info(f"Generated backstory for {bird_name}")
            return backstory
        except Exception as e:
            logger.error(f"Error generating bird backstory: {e}")
            return None
    
    def generate_name_and_backstory(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate both a name and backstory for a bird.
        
        Returns:
            Tuple of (name, backstory). Either or both may be None if generation fails.
        """
        name = self.generate_bird_name()
        if name:
            backstory = self.generate_bird_backstory(name)
            return name, backstory
        return None, None

