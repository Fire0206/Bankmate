import json
from pathlib import Path

from finorch_api.main import app

repository_root = Path(__file__).resolve().parents[3]
output_path = repository_root / "apps" / "web" / "openapi.json"
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(
    json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print(f"Wrote OpenAPI schema to {output_path.relative_to(repository_root)}")
