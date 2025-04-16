import os
import yaml
from datetime import datetime, time, timedelta
import logging
from typing import List, Dict, Optional, Tuple, Any

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Define data directory
data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
opening_hours_dir = os.path.join(data_dir, 'opening_hours')

# Ensure directories exist
os.makedirs(opening_hours_dir, exist_ok=True)
for pool_name, _ in [("Hallenbad Oerlikon", "SSD-7"),
                     ("Hallenbad City", "SSD-4"),
                     ("Hallenbad Blaesi", "SSD-2")]:
    pool_dir = os.path.join(opening_hours_dir, pool_name.lower().replace(' ', '_'))
    os.makedirs(pool_dir, exist_ok=True)


def parse_time(time_str: str) -> time:
    """Convert a time string (HH:MM) to a datetime.time object."""
    hour, minute = map(int, time_str.split(':'))
    return time(hour=hour, minute=minute)


def is_pool_open(pool_name: str, check_datetime: datetime) -> bool:
    """
    Check if a pool is open at a specific datetime.

    Args:
        pool_name: Name of the pool (e.g., "Hallenbad Oerlikon")
        check_datetime: Datetime to check if pool is open

    Returns:
        bool: True if the pool is open, False otherwise
    """
    # Get the pool's schedules
    regular_schedule = get_regular_schedule(pool_name, check_datetime.date())
    exceptions = get_exceptions(pool_name, check_datetime.date())

    # Check date in exceptions first
    if exceptions:
        return is_open_at_time(exceptions['schedule'], check_datetime.time())

    # If no exception, check regular schedule
    if regular_schedule:
        day_of_week = check_datetime.strftime('%A')  # Monday, Tuesday, etc.
        if day_of_week in regular_schedule:
            return is_open_at_time(regular_schedule[day_of_week], check_datetime.time())

    # If we can't determine or no schedule found, assume closed
    return False


def is_open_at_time(schedule: List[Dict[str, str]], check_time: time) -> bool:
    """
    Check if a specific time falls within any of the open periods in a schedule.

    Args:
        schedule: List of open periods with open/close times
        check_time: Time to check

    Returns:
        bool: True if the time is within an open period, False otherwise
    """
    if not schedule:  # Empty schedule means closed
        return False

    for period in schedule:
        open_time = parse_time(period['open'])
        close_time = parse_time(period['close'])

        # Handle cases where closing time is on the next day
        if close_time < open_time:
            if (check_time >= open_time) or (check_time < close_time):
                return True
        else:
            if open_time <= check_time < close_time:
                return True

    return False


def get_regular_schedule(pool_name: str, date: datetime.date) -> Optional[Dict[str, List[Dict[str, str]]]]:
    """
    Get the regular schedule for a pool that is valid for a specific date.

    Args:
        pool_name: Name of the pool
        date: Date to check for valid schedule

    Returns:
        Optional[Dict]: Schedule for each day of the week or None if not found
    """
    pool_dir = os.path.join(opening_hours_dir, pool_name.lower().replace(' ', '_'))
    regular_file = os.path.join(pool_dir, 'regular.yaml')

    if not os.path.exists(regular_file):
        logging.warning(f"No regular schedule file found for {pool_name}")
        return None

    try:
        with open(regular_file, 'r') as file:
            schedules = yaml.safe_load(file)

        for schedule in schedules:
            valid_from = datetime.strptime(schedule['valid_from'], '%Y-%m-%d').date()
            valid_until = None
            if schedule['valid_until']:
                valid_until = datetime.strptime(schedule['valid_until'], '%Y-%m-%d').date()

            # Check if the date falls within this schedule's validity period
            if valid_from <= date and (valid_until is None or date <= valid_until):
                return schedule['schedule']

        logging.warning(f"No valid schedule found for {pool_name} on {date}")
        return None

    except Exception as e:
        logging.error(f"Error loading regular schedule for {pool_name}: {e}")
        return None


def get_exceptions(pool_name: str, date: datetime.date) -> Optional[Dict[str, Any]]:
    """
    Get any exception schedule for a pool on a specific date.

    Args:
        pool_name: Name of the pool
        date: Date to check for exceptions

    Returns:
        Optional[Dict]: Exception schedule for the date or None if not found
    """
    pool_dir = os.path.join(opening_hours_dir, pool_name.lower().replace(' ', '_'))
    exceptions_file = os.path.join(pool_dir, 'exceptions.yaml')

    if not os.path.exists(exceptions_file):
        return None

    try:
        with open(exceptions_file, 'r') as file:
            exceptions = yaml.safe_load(file)

        date_str = date.strftime('%Y-%m-%d')

        for exception in exceptions:
            # Check for single day exceptions
            if exception.get('type') == 'single_day' and exception.get('date') == date_str:
                return exception

            # Check for date range exceptions
            elif exception.get('type') == 'date_range':
                start_date = datetime.strptime(exception.get('start_date'), '%Y-%m-%d').date()
                end_date = datetime.strptime(exception.get('end_date'), '%Y-%m-%d').date()

                if start_date <= date <= end_date:
                    return exception

            # For backwards compatibility with older format
            elif 'date' in exception and exception['date'] == date_str:
                return exception

        return None

    except Exception as e:
        logging.error(f"Error loading exceptions for {pool_name}: {e}")
        return None


def get_closed_periods(pool_name: str,
                       start_date: datetime.date,
                       end_date: datetime.date) -> List[Tuple[datetime, datetime]]:
    """
    Get all closed periods for a pool within a date range.

    Args:
        pool_name: Name of the pool
        start_date: Start date of the range to check
        end_date: End date of the range to check

    Returns:
        List[Tuple[datetime, datetime]]: List of (start, end) tuples for closed periods
    """
    closed_periods = []
    current_date = start_date

    # Iterate through each day in the range
    while current_date <= end_date:
        day_start = datetime.combine(current_date, time(0, 0))
        day_end = datetime.combine(current_date, time(23, 59, 59))

        # Get the schedule for this day
        regular_schedule = get_regular_schedule(pool_name, current_date)
        exceptions = get_exceptions(pool_name, current_date)

        # Determine the active schedule for this day
        active_schedule = None
        if exceptions:
            active_schedule = exceptions['schedule']
        elif regular_schedule:
            day_of_week = current_date.strftime('%A')
            if day_of_week in regular_schedule:
                active_schedule = regular_schedule[day_of_week]

        # If no schedule or empty schedule, the pool is closed all day
        if not active_schedule:
            closed_periods.append((day_start, day_end))
            current_date += timedelta(days=1)
            continue

        # Find closed periods within this day
        periods = []
        time_cursor = time(0, 0)

        # Sort open periods by start time
        sorted_schedule = sorted(active_schedule, key=lambda x: parse_time(x['open']))

        for period in sorted_schedule:
            open_time = parse_time(period['open'])

            # If there's a gap before this open period, add it as a closed period
            if open_time > time_cursor:
                closed_start = datetime.combine(current_date, time_cursor)
                closed_end = datetime.combine(current_date, open_time)
                periods.append((closed_start, closed_end))

            # Move cursor to the end of this open period
            time_cursor = parse_time(period['close'])

            # Handle overnight periods
            if time_cursor < open_time:  # This means it extends to the next day
                # No closed period to add here, we'll handle the next day separately
                break

        # If the last open period ends before midnight, add the remainder as closed
        if time_cursor < time(23, 59, 59):
            closed_start = datetime.combine(current_date, time_cursor)
            closed_end = day_end
            periods.append((closed_start, closed_end))

        # Add all closed periods for this day
        closed_periods.extend(periods)

        # Move to the next day
        current_date += timedelta(days=1)

    return closed_periods


# Function for sample file creation removed as requested

if __name__ == "__main__":
    # Test if a pool is open now
    now = datetime.now()
    for pool_name, _ in [("Hallenbad Oerlikon", "SSD-7"),
                         ("Hallenbad City", "SSD-4"),
                         ("Hallenbad Blaesi", "SSD-2")]:
        is_open = is_pool_open(pool_name, now)
        print(f"{pool_name} is {'open' if is_open else 'closed'} at {now}")

        # Get closed periods for the next 7 days
        start = now.date()
        end = (now + timedelta(days=7)).date()
        closed = get_closed_periods(pool_name, start, end)
        print(f"Found {len(closed)} closed periods in the next 7 days")
