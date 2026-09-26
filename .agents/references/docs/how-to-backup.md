# How to Backup and Export IsaacLab-Arena

This guide describes how to create a clean, lightweight zip backup of the active repository branch without Git internal metadata (`.git/`) or large generated artifacts, and how to initialize it as a fresh, standalone GitHub project.

---

## 1. Directory Context & Footprint

When creating an archive of this repository, be aware of high-footprint directories that should **not** be packed into a code backup:

| Directory | Typical Size | Description / Exclusion Reason |
| :--- | :---: | :--- |
| `.git/` | **~4.8 GB** | Local Git commit history and packfiles (not needed for fresh repository initialization). |
| `submodules/` | **~17 GB** | Vendored checkouts ([`IsaacLab`](../../../submodules/IsaacLab) and [`Isaac-GR00T`](../../../submodules/Isaac-GR00T)). Stored as pointers in `.gitmodules`. |
| `outputs/` | **~5.2 GB** | Simulation runs, PhysX trajectories, camera PNG captures, and execution logs. |

A properly filtered archive is only **~110–130 MB**.

---

## 2. Paths & Environment Setup

- **Host Source Path**: `/home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena`
- **Host Destination Path**: `/home/tarfy/Documents/ArenaBackup`
- **Devcontainer Mount Path**: `/workspaces/IsaacLab-Arena`

> [!NOTE]
> If running from the host terminal, paths under `/home/tarfy/...` can be accessed directly. If executing from inside the devcontainer shell, write outputs to `/workspaces/IsaacLab-Arena/` so they immediately appear in the mounted host directory.

---

## 3. Step-by-Step Backup Instructions

### Step 1: Create the Backup Destination Directory
On the host terminal:
```bash
mkdir -p /home/tarfy/Documents/ArenaBackup
```

### Step 2: Navigate to the Repository Root
```bash
cd /home/tarfy/Documents/GitHub/BoredEngineer/IsaacLab-Arena
```

### Step 3: Create the Archive

#### Option A: Clean Git Archive (Recommended)
This method exports all tracked files, preserves lightweight [`.gitmodules`](../../../.gitmodules) pointers, and automatically ignores `.git/`, `outputs/`, and submodule disk clones.

By using `git stash create`, **uncommitted changes and newly added untracked files are captured into the backup without mutating branch history**:

```bash
# 1. Stage all changes (including untracked files)
git add -A

# 2. Generate a temporary tree snapshot commit hash (does not alter git branch history)
TREE_SHA=$(git stash create)

# 3. Create the clean zip directly into the backup destination
git archive --format=zip -o /home/tarfy/Documents/ArenaBackup/isaaclab_arena_backup.zip ${TREE_SHA:-HEAD}

# 4. Unstage to restore working tree to its clean pre-stage state
git reset
```

#### Option B: Filesystem Zip with Exclusions
If archiving directly with the `zip` utility without Git:

```bash
zip -r /home/tarfy/Documents/ArenaBackup/isaaclab_arena_backup.zip . \
  -x ".git/*" \
  -x "submodules/*" \
  -x "outputs/*" \
  -x "**/__pycache__/*" \
  -x "*.pyc" \
  -x ".cache/*"
```

---

## 4. Initializing as a New Standalone GitHub Project

To initialize a new GitHub repository from the generated backup:

```bash
# 1. Navigate to the backup directory
cd /home/tarfy/Documents/ArenaBackup

# 2. Extract the archive
unzip isaaclab_arena_backup.zip

# 3. (Optional) Remove the archive file
rm isaaclab_arena_backup.zip

# 4. Initialize a fresh Git repository on main
git init -b main

# 5. Stage and create the initial commit
git add .
git commit -m "Initial commit of IsaacLab-Arena"

# 6. Add your new remote repository and push
git remote add origin git@github.com:<your-org-or-username>/<your-new-repo>.git
git push -u origin main
```

---

## 5. Rehydrating Submodules in the New Repository

The archive retains the root [`.gitmodules`](../../../.gitmodules) file. To clone the exact versions of the submodules into your new project without manual download:

```bash
cd /home/tarfy/Documents/ArenaBackup
git submodule update --init --recursive
```
*(If your new project requires pointing submodules to different forks or URLs, update the URLs in `.gitmodules` before running `submodule update`.)*
