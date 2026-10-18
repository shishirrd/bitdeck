import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        from bitdeck.packaged_check import main
    else:
        from bitdeck.desktop import main
    raise SystemExit(main())
