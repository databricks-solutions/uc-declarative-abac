from pathlib import Path

app_name = "ABAC Policy Explorer"
app_entrypoint = "abac_viewer.backend.app:app"
app_slug = "abac_viewer"
api_prefix = "/api"
dist_dir = Path(__file__).parent / "__dist__"
