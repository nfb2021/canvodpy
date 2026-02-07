# Marimo State Management Explanation

## The Problem: Why Normal Variables Don't Work

### Marimo's Reactive Model

Marimo treats each cell as a **pure function** that automatically re-runs when dependencies change:

```python
# Cell 1
x = 5

# Cell 2
y = x + 10  # Automatically updates when x changes
```

### The Conditional Assignment Problem

```python
# Cell A
if button.value:
    result = expensive_computation()  # Only defined when button = True

# Cell B
print(result)  # ❌ ERROR: 'result' doesn't exist when button = False
```

**Why this fails:**
- When `button.value` is `False`, the variable `result` is **never created**
- Cell B tries to reference `result` but it doesn't exist in the namespace
- Marimo can't create a dependency graph because `result` isn't always defined

## The Solution: `mo.state()`

### What `mo.state()` Does

Creates a **persistent container** that:
1. **Always exists** (even when empty)
2. **Survives across cell executions**
3. **Can be read/written from any cell**

```python
# Define state (do this ONCE in its own cell)
my_state = mo.state(None)  # Initial value: None

# Write to state (in button handler)
if button.value:
    my_state.value = downloaded_data

# Read from state (in separate cell)
if my_state.value is not None:
    process(my_state.value)
```

### Key Insight

- `my_state` (the container) is **always defined**
- `my_state.value` (the contents) can be `None` or any value
- Other cells can safely check `my_state.value` without conditional errors

## Complete Working Example: Two-Step Download + Read

### Step 1: Define State (ONCE)

```python
@app.cell
def _(mo):
    from canvod.auxiliary.ephemeris.reader import Sp3File

    # State container - always exists, starts as None
    sp3_state = mo.state(None)

    return Sp3File, sp3_state
```

**Why this works:**
- `sp3_state` is defined unconditionally
- It's returned from the cell so other cells can access it
- Initial value `None` indicates "no file downloaded yet"

### Step 2: Download Handler (WRITE to state)

```python
@app.cell
def _(mo):
    download_button = mo.ui.button(label="Download SP3")
    download_button
    return (download_button,)

@app.cell
def _(sp3_state, download_button, ...):
    if download_button.value:
        try:
            # Download file
            _file = Sp3File.from_datetime_date(...)

            # CRITICAL: Store in state
            sp3_state.value = _file

            output = mo.md("✅ Downloaded successfully")
        except Exception as e:
            # On error: keep state as None
            sp3_state.value = None
            output = mo.md(f"❌ Error: {e}")
    else:
        output = mo.md("Click button to download")

    output
```

**Why this works:**
- `sp3_state` container always exists (defined in Step 1)
- We write to `sp3_state.value` on successful download
- On error, we explicitly set `sp3_state.value = None`
- No variables are conditionally defined - only the state contents change

### Step 3: Read Handler (READ from state)

```python
@app.cell
def _(mo):
    read_button = mo.ui.button(label="Read Dataset")
    read_button
    return (read_button,)

@app.cell
def _(sp3_state, read_button):
    if read_button.value:
        if sp3_state.value is not None:
            # File exists in state - safe to use
            try:
                dataset = sp3_state.value.data
                output = mo.md(f"Dimensions: {dict(dataset.sizes)}")
            except Exception as e:
                output = mo.md(f"❌ Error: {e}")
        else:
            # State is None - file not downloaded
            output = mo.md("⚠️ Download file first")
    else:
        output = mo.md("Click button to read")

    output
```

**Why this works:**
- We check `sp3_state.value is not None` before accessing
- No conditional variable definitions
- Clear error handling for each case

## Common Mistakes

### ❌ Mistake 1: Returning state from conditional

```python
@app.cell
def _(button):
    if button.value:
        state = mo.state(None)  # Only created when button clicked
        return (state,)  # Other cells can't access this
```

**Fix:** Define state unconditionally in its own cell.

### ❌ Mistake 2: Trying to return values from conditionals

```python
@app.cell
def _(button):
    if button.value:
        result = compute()
        return (result,)  # Doesn't make result available when button = False
    else:
        return (None,)  # Can't return different things
```

**Fix:** Use state to store results, don't try to return from conditionals.

### ❌ Mistake 3: Not checking state before access

```python
@app.cell
def _(sp3_state):
    dataset = sp3_state.value.data  # Crashes if value is None!
```

**Fix:** Always check `if sp3_state.value is not None:` first.

## Pattern Summary

### The Three-Cell Pattern

1. **State Definition Cell** (runs once)
   ```python
   state_container = mo.state(initial_value)
   return (state_container,)
   ```

2. **Write Cell** (triggered by button/input)
   ```python
   if trigger.value:
       state_container.value = new_data
   ```

3. **Read Cell** (uses state)
   ```python
   if state_container.value is not None:
       use(state_container.value)
   ```

### Why This Works

- **State container** is always defined (Step 1)
- **State contents** can change without re-defining variables (Step 2)
- **Other cells** can safely check contents without errors (Step 3)
- **Marimo's reactivity** still works - cells re-run when state changes

## Applied to canvod-auxiliary Demo

The demo uses this pattern for file operations:

1. **State init:** `sp3_state = mo.state(None)` and `clk_state = mo.state(None)`
2. **Download:** Button click → `from_datetime_date()` → `sp3_state.value = file_object`
3. **Read:** Button click → check `sp3_state.value is not None` → call `.data` property

This enables the two-step workflow:
- **Step 1:** Download file (get file path, metadata)
- **Step 2:** Read dataset (lazy-load with `.data` property)

Without state management, Step 2 couldn't access the file object from Step 1.
