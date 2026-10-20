# Builds the customer demo zip. Arguments pass through to demo_package.py
# (--keys-file, --out).
Set-Location "$PSScriptRoot\.."
uv run python scripts/demo_package.py @args
exit $LASTEXITCODE
