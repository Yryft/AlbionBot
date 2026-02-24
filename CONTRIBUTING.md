## Contributing

- Keep features isolated in modules under `src/albionbot/modules/`.
- Prefer pure logic helpers + minimal Discord I/O in modules.
- Configuration goes in `src/albionbot/config.py`.
- Persistence goes through `src/albionbot/storage/store.py` (JSON for now).
