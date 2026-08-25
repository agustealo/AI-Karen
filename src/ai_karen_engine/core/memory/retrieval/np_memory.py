import json
from typing import Any

from tqdm import tqdm

from ai_karen_engine.core.logging import get_logger

try:
    import torch
    import torch.nn.functional as F
    from transformers import AutoModel, AutoTokenizer

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]
    AutoTokenizer = AutoModel = Any  # type: ignore[assignment]

logger = get_logger(__name__)

def _ensure_torch_available() -> None:
    if not TORCH_AVAILABLE or torch is None:
        raise RuntimeError(
            "Torch and transformers are required for embedding operations, but they are "
            "not installed. Install optional ML dependencies to enable this feature."
        )


# Conditional decorator for torch.no_grad()
def conditional_no_grad():
    """Decorator that uses torch.no_grad() if available, otherwise does nothing."""

    if TORCH_AVAILABLE and torch is not None:
        return torch.no_grad()

    def identity_decorator(func):
        return func

    return identity_decorator


def load_jsonl(path: str) -> list[dict]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items.append(obj)
            except Exception as e:
                logger.warning(f"Failed to parse line {ln} in {path}, skipped: {e}")
    return items


def extract_pairs(items: list[dict], key_field: str, value_field: str) -> list[tuple[str, object, int]]:
    pairs = []
    for i, obj in enumerate(items):
        if key_field in obj and value_field in obj:
            pairs.append((str(obj[key_field]), obj[value_field], i))
        elif len(obj) == 2:
            ks = list(obj.keys())
            pairs.append((str(obj[ks[0]]), obj[ks[1]], i))
        else:
            pass
    return pairs


@conditional_no_grad()
def embed_texts(
    texts: list[str],
    tokenizer,
    model,
    device,
    batch_size: int = 64,
    max_length: int = 256,
):
    _ensure_torch_available()

    vecs = []
    model.eval()
    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding"):
        batch = texts[i : i + batch_size]
        enc = tokenizer(
            batch, padding=True, truncation=True, max_length=max_length, return_tensors="pt"
        )
        enc = {k: v.to(device) for k, v in enc.items()}
        out = model(**enc, return_dict=True)
        if hasattr(out, "pooler_output") and out.pooler_output is not None:
            e = out.pooler_output
        else:
            e = out.last_hidden_state[:, 0, :]
        if F is None:
            raise RuntimeError(
                "torch.nn.functional is unavailable; install optional ML dependencies to "
                "normalize embeddings."
            )
        e = F.normalize(e, p=2, dim=1)
        vecs.append(e.cpu())
    return torch.cat(vecs, dim=0)


def retrieve(
    task: str,
    pairs: list[tuple[str, object, int]],
    tokenizer, 
    model,
    device_str: str = "auto",
    top_k: int = 5,
    max_length: int = 256,
) -> list[dict]:
    _ensure_torch_available()

    if device_str == "cpu":
        device = torch.device("cpu")
    elif device_str == "cuda" and torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    keys = [p[0] for p in pairs] 
    key_vecs = embed_texts(keys, tokenizer, model, device, max_length=max_length)
    query_vec = embed_texts([task], tokenizer, model, device, max_length=max_length)[0].unsqueeze(0)

    sims = (query_vec @ key_vecs.T).squeeze(0) 
    k = min(top_k, len(pairs))
    topk_scores, topk_idx = torch.topk(sims, k)

    results = []
    for rank, (score, idx) in enumerate(zip(topk_scores.tolist(), topk_idx.tolist()), 1):
        key, value, line_index = pairs[idx] 
        results.append(
            {
                "rank": rank,
                "score": round(float(score), 6),
                "question": key,
                "plan": value,
                "line_index": line_index,  
            }
        )
    return results
