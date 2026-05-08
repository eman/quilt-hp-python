# Configure schedules

Schedules consist of two objects: `ScheduleDay` (a named program with time-based events) and `ScheduleWeek` (a mapping of weekdays to day programs). A space can have one active schedule week.

For the `ScheduleDay`, `ScheduleWeek`, `ScheduleEvent`, and `ScheduleWeekDay` model fields, see [Models reference](../reference/models.md).

---

## Create a schedule day with events

To create a day program with timed comfort-setting transitions:

```python
from quilt_hp.models.schedule import ScheduleEvent

# Get a comfort setting ID from the snapshot
snapshot = await client.get_snapshot()
space = snapshot.space_by_name("Bedroom")
active_cs = next(
    cs for cs in snapshot.comfort_settings.values() if cs.name == "Active"
)
sleep_cs = next(
    cs for cs in snapshot.comfort_settings.values() if cs.name == "Sleep"
)

events = [
    ScheduleEvent(time_of_day_s=7 * 3600, comfort_setting_id=active_cs.id),   # 07:00 → Active
    ScheduleEvent(time_of_day_s=22 * 3600, comfort_setting_id=sleep_cs.id),   # 22:00 → Sleep
]

day = await client.create_schedule_day(
    space_id=space.id,
    name="Weekday",
    events=events,
)
print(f"Created schedule day: {day.id} ({len(day.events)} events)")
```

`time_of_day_s` is the number of seconds from midnight (e.g., `7 * 3600` = 07:00).

---

## Assign schedule days to a week

To create a schedule week and assign day programs to each weekday:

```python
from quilt_hp.models.schedule import ScheduleWeekDay

# day_of_week: 0 = Monday, 6 = Sunday
week = await client.create_schedule_week(
    space_id=space.id,
    days=[
        ScheduleWeekDay(day_of_week=0, schedule_day_id=weekday_program.id),  # Mon
        ScheduleWeekDay(day_of_week=1, schedule_day_id=weekday_program.id),  # Tue
        ScheduleWeekDay(day_of_week=2, schedule_day_id=weekday_program.id),  # Wed
        ScheduleWeekDay(day_of_week=3, schedule_day_id=weekday_program.id),  # Thu
        ScheduleWeekDay(day_of_week=4, schedule_day_id=weekday_program.id),  # Fri
        ScheduleWeekDay(day_of_week=5, schedule_day_id=weekend_program.id),  # Sat
        ScheduleWeekDay(day_of_week=6, schedule_day_id=weekend_program.id),  # Sun
    ],
)
print(f"Created schedule week: {week.id}")
```

---

## Update a schedule week

To replace the day assignments in an existing schedule week:

```python
updated_week = await client.update_schedule_week(
    schedule_week_id=week.id,
    space_id=space.id,
    days=[
        ScheduleWeekDay(day_of_week=0, schedule_day_id=new_monday_program.id),
        # ... include all 7 days; omitted days are cleared
    ],
)
```

---

## Delete a schedule day or week

To delete a schedule day program:

```python
await client.delete_schedule_day(schedule_day_id=day.id)
```

To delete a schedule week:

```python
await client.delete_schedule_week(schedule_week_id=week.id)
```

Deleting a schedule week does not delete the day programs it references.

---

## Pause and resume schedule execution

To pause all schedules across the entire system:

```python
await client.set_schedule_execution(paused=True)
```

To resume:

```python
await client.set_schedule_execution(paused=False)
```

This is a global switch. It affects all schedule weeks across all spaces in the system. The current pause state is available as `snapshot.schedule_paused`.
