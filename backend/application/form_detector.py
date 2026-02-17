"""Detect and classify all form fields on a page using Playwright."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Field type classification
# ---------------------------------------------------------------------------

_INPUT_TYPE_MAP: dict[str, str] = {
    "text": "text",
    "email": "email",
    "tel": "tel",
    "number": "number",
    "date": "date",
    "range": "range",
    "file": "file",
    "radio": "radio",
    "checkbox": "checkbox",
    "hidden": "hidden",
    "password": "password",
    "url": "url",
    "search": "text",
    "color": "text",
    "month": "date",
    "week": "date",
    "time": "date",
    "datetime-local": "date",
}


async def detect_fields(page: Any) -> list[dict]:
    """
    Detect and classify all interactive form fields on the current page.

    For each field returns a dict:
        {
            "type": str,        # text | email | tel | textarea | select | radio | checkbox | file | range | date | number
            "name": str,        # from name or id attribute
            "label": str,       # from <label for=...>, aria-label, placeholder, or closest text
            "required": bool,   # from required / aria-required attributes
            "options": list,    # for select/radio elements only
            "ref": str,         # CSS selector for interaction
            "tag": str,         # raw HTML tag (input, select, textarea)
            "visible": bool,    # element is visible
        }
    """
    try:
        fields: list[dict] = await page.evaluate(_JS_DETECT_FIELDS)
        log.info(
            "form_detector.detected",
            field_count=len(fields),
            url=page.url,
        )
        return fields
    except Exception as e:
        log.error("form_detector.failed", error=str(e), url=page.url)
        return []


async def get_conditional_fields(
    page: Any,
    timeout_ms: int = 3000,
) -> list[dict]:
    """
    Detect fields that appear after user interaction or dynamic page updates.

    Waits up to timeout_ms for any new form fields to become visible,
    then returns the full field list including conditionally revealed fields.
    """
    initial_fields = await detect_fields(page)
    initial_refs = {f.get("ref", "") for f in initial_fields}

    try:
        # Wait for potential dynamic content to load
        await page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        # Timeout is acceptable here — page may never reach networkidle
        pass

    all_fields = await detect_fields(page)
    new_fields = [f for f in all_fields if f.get("ref", "") not in initial_refs]

    if new_fields:
        log.info(
            "form_detector.conditional_fields_found",
            new_count=len(new_fields),
            url=page.url,
        )

    return all_fields


# ---------------------------------------------------------------------------
# JavaScript executed in browser context
# ---------------------------------------------------------------------------

_JS_DETECT_FIELDS = """
() => {
    const fields = [];
    const seen = new Set();

    function getLabel(el) {
        // 1. aria-label
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

        // 2. aria-labelledby
        const labelledById = el.getAttribute('aria-labelledby');
        if (labelledById) {
            const labelEl = document.getElementById(labelledById);
            if (labelEl) return labelEl.textContent.trim();
        }

        // 3. <label for="id">
        const id = el.id;
        if (id) {
            const labelEl = document.querySelector(`label[for="${id}"]`);
            if (labelEl) return labelEl.textContent.trim();
        }

        // 4. Wrapping <label>
        const parentLabel = el.closest('label');
        if (parentLabel) {
            const text = parentLabel.textContent.replace(el.value || '', '').trim();
            if (text) return text;
        }

        // 5. placeholder
        const placeholder = el.getAttribute('placeholder');
        if (placeholder && placeholder.trim()) return placeholder.trim();

        // 6. Nearest preceding text node or label-like element
        let prev = el.previousElementSibling;
        for (let i = 0; i < 3 && prev; i++) {
            const text = prev.textContent.trim();
            if (text && text.length < 80) return text;
            prev = prev.previousElementSibling;
        }

        // 7. name attribute as fallback
        return el.name || el.id || '';
    }

    function getSelector(el) {
        // Build a unique CSS selector
        if (el.id) return `#${CSS.escape(el.id)}`;
        if (el.name) {
            const tag = el.tagName.toLowerCase();
            const matches = document.querySelectorAll(`${tag}[name="${el.name}"]`);
            if (matches.length === 1) return `${tag}[name="${CSS.escape(el.name)}"]`;
            // Add index if multiple with same name
            const idx = Array.from(matches).indexOf(el);
            return `${tag}[name="${CSS.escape(el.name)}"]:nth-of-type(${idx + 1})`;
        }
        // Fallback: positional selector
        const tag = el.tagName.toLowerCase();
        const siblings = Array.from(el.parentElement
            ? el.parentElement.querySelectorAll(tag)
            : document.querySelectorAll(tag));
        const idx = siblings.indexOf(el);
        return idx >= 0 ? `${tag}:nth-of-type(${idx + 1})` : tag;
    }

    function isVisible(el) {
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (parseFloat(style.opacity) === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }

    // Process <input> elements
    document.querySelectorAll('input').forEach(el => {
        const type = (el.type || 'text').toLowerCase();
        if (type === 'hidden' || type === 'submit' || type === 'button' || type === 'image') return;
        const ref = getSelector(el);
        if (seen.has(ref)) return;
        seen.add(ref);

        fields.push({
            tag: 'input',
            type: type === 'text' ? 'text'
                : type === 'email' ? 'email'
                : type === 'tel' ? 'tel'
                : type === 'number' ? 'number'
                : type === 'date' || type === 'month' || type === 'week' || type === 'datetime-local' ? 'date'
                : type === 'range' ? 'range'
                : type === 'file' ? 'file'
                : type === 'radio' ? 'radio'
                : type === 'checkbox' ? 'checkbox'
                : 'text',
            name: el.name || el.id || '',
            label: getLabel(el),
            required: el.required || el.getAttribute('aria-required') === 'true',
            options: [],
            ref: ref,
            visible: isVisible(el),
            value: type !== 'password' ? (el.value || '') : '',
        });
    });

    // Process <textarea> elements
    document.querySelectorAll('textarea').forEach(el => {
        const ref = getSelector(el);
        if (seen.has(ref)) return;
        seen.add(ref);
        fields.push({
            tag: 'textarea',
            type: 'textarea',
            name: el.name || el.id || '',
            label: getLabel(el),
            required: el.required || el.getAttribute('aria-required') === 'true',
            options: [],
            ref: ref,
            visible: isVisible(el),
            value: el.value || '',
        });
    });

    // Process <select> elements
    document.querySelectorAll('select').forEach(el => {
        const ref = getSelector(el);
        if (seen.has(ref)) return;
        seen.add(ref);
        const options = Array.from(el.options)
            .filter(opt => opt.value !== '')
            .map(opt => ({ value: opt.value, text: opt.text.trim() }));
        fields.push({
            tag: 'select',
            type: 'select',
            name: el.name || el.id || '',
            label: getLabel(el),
            required: el.required || el.getAttribute('aria-required') === 'true',
            options: options,
            ref: ref,
            visible: isVisible(el),
            value: el.value || '',
        });
    });

    return fields;
}
"""
