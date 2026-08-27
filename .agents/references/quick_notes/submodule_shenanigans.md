# Git Submodule Shenanigans & Fork Guide

This guide documents the Git submodule mental model, how to track and commit submodule changes using a personal fork (`boredengineering/Isaac-GR00T`), and how to recover if anything goes wrong.

---

## 1. Core Mental Model

A Git submodule is a standalone Git repository nested inside a folder of a parent repository (`IsaacLab-Arena`).

```
IsaacLab-Arena (Parent Repository)
│
├── .gitmodules                     <-- Maps folder paths to remote repository URLs
├── isaaclab_arena/
└── submodules/
    └── Isaac-GR00T/                <-- Independent Git repository (tracks its own commits)
```

The parent repository **does NOT track files** inside the submodule folder. Instead, it tracks only two things:
1. The remote URL configured in `.gitmodules`.
2. A single commit SHA-1 hash (a "gitlink" / pointer) representing the exact state to checkout.

### The Golden Rule of Submodules

```
┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────────┐
│ 1. Commit inside Submodule │ ───> │ 2. PUSH Submodule to Fork │ ───> │ 3. Commit & Push in Root Repo │
└───────────────────────────┘      └───────────────────────────┘      └───────────────────────────────┘
```

> **CRITICAL:** Always push the submodule commits to GitHub *before* committing and pushing the parent repository. If you update the submodule pointer in the main repo without pushing the submodule commits to a public remote, collaborators and CI will fail with `fatal: reference is not a tree`.

---

## 2. Why "Detached HEAD" Happens

When `IsaacLab-Arena` initializes submodules, Git checks out the exact commit hash tracked by the parent repository rather than a named branch (e.g. `main` or `dev`). This leaves the submodule in a **detached HEAD** state.

Furthermore, the default remote points to `git@github.com:NVIDIA/Isaac-GR00T.git` (where you lack write/push permissions).

To make persistent changes, you must:
1. Point your submodule remote to your fork (`boredengineering/Isaac-GR00T`).
2. Create a named branch from the current detached HEAD commit.
3. Push your commits to your fork.

---

## 3. Step-by-Step: Switch Submodule to Your Fork

### Step 1: Configure Remotes and Create a Branch in the Submodule

```bash
cd submodules/Isaac-GR00T

# 1. Rename upstream origin (NVIDIA) so you can still fetch updates later
git remote rename origin upstream

# 2. Add your fork as origin
git remote add origin git@github.com:boredengineering/Isaac-GR00T.git
# (or via HTTPS: git remote add origin https://github.com/boredengineering/Isaac-GR00T.git)

# 3. Create and switch to a new branch from the current detached HEAD
git checkout -b dev/arena-compat
```

### Step 2: Commit and Push Changes to Your Fork

```bash
# Check modified files
git status
git diff

# Stage and commit your changes inside the submodule
git add .
git commit -m "Update Isaac-GR00T scripts and config for Arena"

# Push the new branch to your fork
git push -u origin dev/arena-compat
```

### Step 3: Update `.gitmodules` in the Parent Repository

Return to the root of `IsaacLab-Arena` and configure `.gitmodules` to point to your fork:

```bash
cd ../..

# Update the submodule URL in .gitmodules
git config --file .gitmodules submodule.submodules/Isaac-GR00T.url git@github.com:boredengineering/Isaac-GR00T.git

# Synchronize local git configuration with .gitmodules
git submodule sync submodules/Isaac-GR00T
```

### Step 4: Commit and Push the Pointer Update in `IsaacLab-Arena`

```bash
# Stage both .gitmodules and the updated submodule pointer
git add .gitmodules submodules/Isaac-GR00T

# Verify what is staged
git status

# Commit and push in the main repo
git commit -m "Point Isaac-GR00T submodule to boredengineering fork"
git push
```

---

## 4. Daily Workflow Cheat Sheet

Whenever making future edits inside `submodules/Isaac-GR00T`:

```bash
# 1. Work and commit inside the submodule
cd submodules/Isaac-GR00T
git add <files>
git commit -m "feat: your submodule change"
git push origin dev/arena-compat          # <-- MUST PUSH FIRST!

# 2. Update pointer in main repo
cd ../..
git add submodules/Isaac-GR00T
git commit -m "chore: update Isaac-GR00T submodule pointer"
git push
```

---

## 5. Syncing Upstream NVIDIA Changes into Your Fork Later

When NVIDIA publishes updates to `Isaac-GR00T`:

```bash
cd submodules/Isaac-GR00T

# Fetch latest from NVIDIA upstream
git fetch upstream

# Merge or rebase onto your working branch
git merge upstream/main
# (or: git rebase upstream/main)

# Push the merged branch to your fork
git push origin dev/arena-compat

# Update the pointer in IsaacLab-Arena
cd ../..
git add submodules/Isaac-GR00T
git commit -m "chore: sync Isaac-GR00T submodule with upstream"
git push
```

---

## 6. Disaster Recovery Playbook ("If We Messed Up")

### Pre-flight Safety Net (Zero-Risk Backup)
Before attempting any major submodule manipulation:

```bash
cd submodules/Isaac-GR00T
# Create a local backup branch at current state
git branch backup-state-$(date +%Y%m%d)
# Stash uncommitted changes if needed
git stash save "backup-uncommitted-changes"
```

---

### Scenario A: "I made messy commits or lost my branch inside the submodule"
Return directly to the original detached commit hash without losing git history:

```bash
cd submodules/Isaac-GR00T

# View git reflog to find any lost commit hash
git reflog

# Force checkout back to the original commit hash
git checkout e29d8fc50b0e4745120ae3fb72447986fe638aa6
```

---

### Scenario B: "The main repo shows dirty / unwanted submodule changes"
Discard uncommitted submodule pointer changes in `IsaacLab-Arena`:

```bash
# In IsaacLab-Arena root:
git restore --staged submodules/Isaac-GR00T
git submodule update --force submodules/Isaac-GR00T
```

---

### Scenario C: "I messed up `.gitmodules` or remote URLs"
Reset `.gitmodules` and restore standard remotes:

```bash
# In IsaacLab-Arena root:
git checkout .gitmodules
git submodule sync

# Inside submodule:
cd submodules/Isaac-GR00T
git remote -v
# Remove unwanted remote:
git remote remove <remote_name>
# Reset origin to NVIDIA:
git remote set-url origin git@github.com:NVIDIA/Isaac-GR00T.git
```

---

### Scenario D: The "Nuclear Option" (Wipe & Re-clone Submodule)
If the submodule state gets tangled beyond quick repair:

```bash
# In IsaacLab-Arena root:
# 1. De-initialize submodule (wipes local directory worktree and config)
git submodule deinit -f submodules/Isaac-GR00T

# 2. Freshly clone and checkout the exact expected commit
git submodule update --init --recursive submodules/Isaac-GR00T
```
