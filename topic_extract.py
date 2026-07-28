from typing import List
import torch

TOPIC_SYS = (
    "You extract short topic tags from a user utterance. "
    "Return 1-3 lowercase tags, comma-separated, no spaces inside tags, no extra text."
)

def extract_topics(model, tokenizer, text: str, max_new_tokens: int = 16) -> List[str]:
    prompt = f"System: {TOPIC_SYS}\n\nUser: {text}\nAssistant:"
    input_ids = tokenizer(prompt, return_tensors="pt").input_ids.to(model.device)
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            do_sample=False,
            max_new_tokens=int(max_new_tokens),
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    cont = out[0, input_ids.shape[-1]:]
    raw = tokenizer.decode(cont, skip_special_tokens=True).strip()
    # split by comma, normalize
    tags = [t.strip().lower() for t in raw.split(",")]
    tags = [t for t in tags if t and t.isascii()]
    # collapse spaces -> hyphens
    tags = [t.replace(" ", "-") for t in tags]
    # basic cleanup
    uniq = []
    for t in tags:
        if t not in uniq:
            uniq.append(t)
    return uniq[:3]
