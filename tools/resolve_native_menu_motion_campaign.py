#!/usr/bin/env python3
"""Compatibility entry point for the Settlement v2.5 campaign resolver.

The motion-only v2.3/v2.4 campaign path was removed.  All callers now resolve
the reproduced structural core and the complete ambient-lifecycle model.
"""

from __future__ import annotations

if __package__:
    from .resolve_native_menu_ambient_campaign import (
        CampaignResolutionError,
        main,
        resolve_campaign,
    )
else:
    from resolve_native_menu_ambient_campaign import (  # type: ignore[no-redef]
        CampaignResolutionError,
        main,
        resolve_campaign,
    )


ResolutionError = CampaignResolutionError


if __name__ == "__main__":
    raise SystemExit(main())
