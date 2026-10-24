"""Human-readable description of a feature's verified demo steps (shared by several modules)."""

from app.schemas.generated.product_profile import Feature

MAX_SUMMARY_CHARS = 160


def summarize_steps(feature: Feature) -> str:
    """Short Vietnamese description of what the verified demo shows, from its steps."""
    parts: list[str] = []
    for step in feature.demo_steps:
        name = ""
        if step.locator is not None:
            name = step.locator.name or step.locator.text or ""
        if step.do == "type":
            parts.append(f"gõ «{step.text or ''}»")
        elif step.do == "click":
            parts.append(f"nhấp «{name}»" if name else "nhấp")
        elif step.do == "dblclick":
            parts.append(f"nhấp đúp «{name}»" if name else "nhấp đúp")
        elif step.do == "upload":
            parts.append("tải một tệp mẫu lên")
        elif step.do == "hover":
            parts.append(f"rê chuột vào «{name}»" if name else "rê chuột")
        elif step.do in ("scroll", "scroll_to"):
            parts.append("cuộn trang")
    if not parts and feature.showcase_target is not None:
        parts.append(f"cuộn tới và làm nổi bật: «{feature.showcase_target.text_quote[:60]}»")
    return " → ".join(parts)[:MAX_SUMMARY_CHARS]
