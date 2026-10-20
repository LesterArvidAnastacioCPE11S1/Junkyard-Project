# Loads settings from a .env file in the project root (if python-dotenv is installed).
# Import this module BEFORE anything that reads os.environ.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass