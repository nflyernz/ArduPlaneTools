# Battery Pack Management

Battery Pack Management lets you identify your physical batteries and link flight logs to them, so APT can build historical battery performance reports.

Select a BIN log using the shared chooser, then open this tab to see which Pack ID is assigned to it. You can select an existing Pack ID, create a new one, or mark the BIN as not tracked. A Pack ID applies to the entire BIN log, not individual flights within it.

You can also rename an existing Pack ID. Renaming updates all saved BIN records that use that Pack ID.

Changes require confirmation. Simply opening the tab, selecting a BIN or refreshing the information does not change saved records. Duplicate or invalid Pack IDs are rejected.

**Record AUTO takeoff history** saves supported takeoff and battery observations from the selected BIN to the assigned battery's history. These saved observations can then be viewed and compared across flight logs in the **Pack Performance** tab.

Recording history requires a BIN with an assigned Pack ID. The action reports how many new observations were saved. Repeating it will not duplicate observations already recorded. Assigning or renaming a Pack ID does not automatically record history.

APT cannot determine which physical battery was installed from the flight log alone. You identify the battery by assigning its Pack ID. Identical copies of a BIN log share the same saved Pack ID, even if their filenames differ.
