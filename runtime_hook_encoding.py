"""PyInstaller runtime hook: set encoding and disable torch.compile early."""

import os

# Force UTF-8 to prevent cp950 decode errors on Traditional Chinese Windows.
os.environ["PYTHONUTF8"] = "1"

# Disable torch.compile / TorchDynamo / Inductor.
# In frozen builds the inductor tries to read kernel template files that
# contain UTF-8 characters, which fail under cp950 locale.  Disabling dynamo
# makes torch.compile() a no-op (returns the model unchanged).
os.environ["TORCH_DISABLE_DYNAMO"] = "1"
os.environ["TORCHDYNAMO_DISABLE"] = "1"
