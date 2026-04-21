from huggingface_hub import HfApi

api = HfApi()

# Create a repository
api.create_repo(
    repo_id="",
    token="your_write_token",
    repo_type="model",  # Options: "model", "dataset", or "space"
    private=False       # Set to True for a private repository
)
