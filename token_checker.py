import os

# File where the Discord bot token will be stored
TOKEN_FILE = "token.txt"

# Minimum length for a Discord bot token (usually 59–60 characters)
MIN_TOKEN_LENGTH = 59

def get_token():
    """
    Checks for an existing token in token.txt.
    If missing, empty, or too short, prompts the user for a new token.
    Saves the new valid token to token.txt.
    Returns the valid token as a string.
    """
    token = None

    # Check if token.txt exists
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
        # Check if token is empty or too short
        if not token or len(token) < MIN_TOKEN_LENGTH:
            print("Existing token is missing or too short. Deleting token.txt.")
            os.remove(TOKEN_FILE)
            token = None
        else:
            print("Valid token found in token.txt")

    # If no valid token, prompt the user
    if not token:
        while True:
            token = input("Enter your Discord bot token: ").strip()
            if len(token) >= MIN_TOKEN_LENGTH:
                with open(TOKEN_FILE, "w") as f:
                    f.write(token)
                print("Token saved to token.txt")
                break
            else:
                print(f"Token too short (must be at least {MIN_TOKEN_LENGTH} chars), try again.")

    return token

# Example usage
if __name__ == "__main__":
    discord_token = get_token()
    print(f"Your Discord token is ready to use: {discord_token[:6]}... (hidden for safety)")