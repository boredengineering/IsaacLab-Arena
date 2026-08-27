# Git Submodule Shenanigans & Fork Guide

This guide documents the Git submodule mental model, how to track and commit submodule changes using personal forks (`boredengineering/Isaac-GR00T` and `boredengineering/IsaacLab`), and how to recover if anything goes wrong.

---

## 1. Core Mental Model

A Git submodule is a standalone Git repository nested inside a folder of a parent repository (`IsaacLab-Arena`).

```
IsaacLab-Arena (Parent Repository)
│
├── .gitmodules                     <-- Maps folder paths to remote repository URLs
├── isaaclab_arena/
└── submodules/
    ├── Isaac-GR00T/                <-- Independent Git repository
    └── IsaacLab/                   <-- Independent Git repository
```

The parent repository **does NOT track files** inside submodule folders. Instead, it tracks only two things:
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

Furthermore, the default remotes point to upstream repositories (`NVIDIA/Isaac-GR00T` and `isaac-sim/IsaacLab`), where you lack write/push permissions.

To make persistent changes, you must:
1. Point your submodule remote to your fork (`boredengineering/*`).
2. Create a named branch from the current detached HEAD commit.
3. Push your commits to your fork.

---

## 3. Step-by-Step: Switch Submodule to Your Fork

### 3.1 `Isaac-GR00T` (`boredengineering/Isaac-GR00T`)

#### Step 1: Configure Remotes and Create Branch
```bash
cd submodules/Isaac-GR00T

# 1. Rename upstream origin (NVIDIA) so you can still fetch updates later
git remote rename origin upstream

# 2. Add your fork as origin
git remote add origin git@github.com:boredengineering/Isaac-GR00T.git
# (or via HTTPS: git remote add origin https://github.com/boredengineering/Isaac-GR00T.git)

# 3. Create and switch to a new branch from the current detached HEAD (e29d8fc)
git checkout -b dev/arena_v0.3.0-compat
```

#### Step 2: Commit and Push Changes to Your Fork
```bash
# Check modified files
git status
git diff

# Stage and commit your changes inside the submodule
git add .
git commit -m "Update Isaac-GR00T scripts and config for Arena"

# Push the new branch to your fork
git push -u origin dev/arena_v0.3.0-compat
```

#### Step 3: Update `.gitmodules` in the Parent Repository
```bash
cd ../..

# Update the submodule URL in .gitmodules
git config --file .gitmodules submodule.submodules/Isaac-GR00T.url git@github.com:boredengineering/Isaac-GR00T.git

# Synchronize local git configuration with .gitmodules
git submodule sync submodules/Isaac-GR00T
```

#### Step 4: Commit and Push the Pointer Update in `IsaacLab-Arena`
```bash
# Stage both .gitmodules and the updated submodule pointer
git add .gitmodules submodules/Isaac-GR00T

# Commit and push in the main repo
git commit -s -m "Point Isaac-GR00T submodule to boredengineering fork"
git push
```

---

### 3.2 `IsaacLab` (`boredengineering/IsaacLab`)

#### Step 1: Configure Remotes and Create Branch
```bash
cd submodules/IsaacLab

# 1. Rename existing origin (isaac-sim) to upstream
git remote rename origin upstream

# 2. Add your fork as origin
git remote add origin git@github.com:boredengineering/IsaacLab.git
# (or via HTTPS: git remote add origin https://github.com/boredengineering/IsaacLab.git)

# 3. Create and switch to a branch from the current commit (ffff603ea / v3.0.0-beta2.patch1)
git checkout -b dev/arena_v0.3.0-compat
```

#### Step 2: Commit and Push Changes to Your Fork
```bash
# (Optional) If you have any edits inside IsaacLab to commit:
# git add .
# git commit -m "Update IsaacLab custom configuration"

# Push the branch to your fork
git push -u origin dev/arena_v0.3.0-compat
```

#### Step 3: Update `.gitmodules` in the Parent Repository
```bash
cd ../..

# Update the submodule URL in .gitmodules
git config --file .gitmodules submodule.submodules/IsaacLab.url git@github.com:boredengineering/IsaacLab.git

# Synchronize local repository configuration
git submodule sync submodules/IsaacLab
```

#### Step 4: Commit and Push in `IsaacLab-Arena`
```bash
# Stage the updated .gitmodules and submodule pointer
git add .gitmodules submodules/IsaacLab

# Commit and push in the parent repository
git commit -s -m "Point IsaacLab submodule to boredengineering fork"
git push
```

---

## 4. Daily Workflow Cheat Sheet

Whenever making future edits inside any submodule (`Isaac-GR00T` or `IsaacLab`):

```bash
# 1. Work and commit inside the submodule
cd submodules/<Submodule-Name>
git add <files>
git commit -m "feat: your submodule change"
git push origin dev/arena_v0.3.0-compat    # <-- MUST PUSH FIRST!

# 2. Update pointer in main repo
cd ../..
git add submodules/<Submodule-Name>
git commit -s -m "chore: update <Submodule-Name> pointer"
git push
```

---

## 5. Syncing Upstream Changes into Your Fork Later

When upstream publishes updates (`NVIDIA/Isaac-GR00T` or `isaac-sim/IsaacLab`):

```bash
cd submodules/<Submodule-Name>

# Fetch latest from upstream
git fetch upstream

# Merge or rebase onto your working branch
git merge upstream/main
# (or: git rebase upstream/main)

# Push the merged branch to your fork
git push origin dev/arena_v0.3.0-compat

# Update the pointer in IsaacLab-Arena
cd ../..
git add submodules/<Submodule-Name>
git commit -s -m "chore: sync <Submodule-Name> with upstream"
git push
```

---

## 6. Disaster Recovery Playbook ("If We Messed Up")

### Pre-flight Safety Net (Zero-Risk Backup)
Before attempting any major submodule manipulation:

```bash
cd submodules/<Submodule-Name>
# Create a local backup branch at current state
git branch backup-state-$(date +%Y%m%d)
# Stash uncommitted changes if needed
git stash save "backup-uncommitted-changes"
```

---

### Scenario A: "I made messy commits or lost my branch inside the submodule"
Return directly to the original detached commit hash without losing git history:

```bash
cd submodules/<Submodule-Name>

# View git reflog to find any lost commit hash
git reflog

# Force checkout back to the original commit hash
# For Isaac-GR00T: git checkout e29d8fc50b0e4745120ae3fb72447986fe638aa6
# For IsaacLab:    git checkout ffff603eafc6b74264a5261cc0183d6a65390d78
```

---

### Scenario B: "The main repo shows dirty / unwanted submodule changes"
Discard uncommitted submodule pointer changes in `IsaacLab-Arena`:

```bash
# In IsaacLab-Arena root:
git restore --staged submodules/<Submodule-Name>
git submodule update --force submodules/<Submodule-Name>
```

---

### Scenario C: "I messed up `.gitmodules` or remote URLs"
Reset `.gitmodules` and restore standard remotes:

```bash
# In IsaacLab-Arena root:
git checkout .gitmodules
git submodule sync

# Inside submodule:
cd submodules/<Submodule-Name>
git remote -v
# Remove unwanted remote:
git remote remove <remote_name>
# Reset origin to original URL:
# For Isaac-GR00T: git remote set-url origin git@github.com:NVIDIA/Isaac-GR00T.git
# For IsaacLab:    git remote set-url origin git@github.com:isaac-sim/IsaacLab.git
```

---

### Scenario D: The "Nuclear Option" (Wipe & Re-clone Submodule)
If the submodule state gets tangled beyond quick repair:

```bash
# In IsaacLab-Arena root:
# 1. De-initialize submodule (wipes local directory worktree and config)
git submodule deinit -f submodules/<Submodule-Name>

# 2. Freshly clone and checkout the exact expected commit
git submodule update --init --recursive submodules/<Submodule-Name>
```
