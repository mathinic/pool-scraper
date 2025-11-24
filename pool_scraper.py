import asyncio
import websockets
import json
import csv
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import opening_hours
from matplotlib.patches import Rectangle

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)

# WebSocket URL and pool mappings
websocket_url = "wss://badi-public.crowdmonitor.ch:9591/api"
pool_mapping = [
    ("Hallenbad Oerlikon", "SSD-7"),
    ("Hallenbad City", "SSD-4"),
    ("Hallenbad Blaesi", "SSD-2")
]

# Define data directory
data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
os.makedirs(data_dir, exist_ok=True)


async def scrape_guest_counts_async():
    """Async function to scrape guest counts for all pools via WebSocket"""
    results = {}

    try:
        # Connect without timeout parameter
        async with websockets.connect(websocket_url) as websocket:
            logging.info("WebSocket connection opened")

            # Send the request to get all data
            await websocket.send("all")

            # Wait for the response
            response = await websocket.recv()

            try:
                data = json.loads(response)

                # Process each pool
                for pool_name, element_id in pool_mapping:
                    for element in data:
                        if element.get('uid') == element_id:
                            count = element.get('currentfill')
                            if count and count != "-":
                                logging.info(f"Found guest count for {pool_name}: {count}")
                                results[pool_name] = count

                                # Get current timestamp
                                zurich_tz = ZoneInfo("Europe/Zurich")

                                timestamp = datetime.now(zurich_tz).strftime('%Y-%m-%d %H:%M:%S')

                                # Prepare CSV file path for this pool
                                pool_filename = pool_name.lower().replace(' ', '_')
                                csv_file = os.path.join(data_dir, f'{pool_filename}_guests.csv')

                                # Check if file exists to determine if headers are needed
                                file_exists = os.path.isfile(csv_file)

                                # Write to CSV
                                with open(csv_file, 'a', newline='') as file:
                                    writer = csv.writer(file)
                                    if not file_exists:
                                        writer.writerow(['Timestamp', 'Number of Guests'])
                                    writer.writerow([timestamp, count])

                                logging.info(f'Data collected for {pool_name}: {count} guests')
                            break

                    if pool_name not in results:
                        logging.warning(f"Couldn't find the guest count element for {pool_name}.")

                return results

            except Exception as e:
                logging.error(f"Error processing WebSocket data: {e}")
                return {}

    except Exception as e:
        logging.error(f"Error in WebSocket connection: {e}")
        return {}


def scrape_guest_counts():
    """Wrapper function to run the async WebSocket function for all pools"""
    try:
        return asyncio.run(scrape_guest_counts_async())
    except Exception as e:
        logging.error(f"Error running async scraper: {e}")
        return {}


def generate_visualization(pool_name):
    """Generate a visualization of the pool guest count data for the last 7 days for a specific pool"""
    pool_filename = pool_name.lower().replace(' ', '_')
    csv_file = os.path.join(data_dir, f'{pool_filename}_guests.csv')
    img_file = os.path.join(data_dir, f'{pool_filename}_visualization.png')

    logging.info(f"Generating visualization for {pool_name}...")

    try:
        # Check if the CSV file exists
        if not os.path.isfile(csv_file):
            logging.warning(f"CSV file for {pool_name} does not exist yet. No visualization generated.")
            return

        # Read the CSV data
        df = pd.read_csv(csv_file)

        if df.empty:
            logging.warning(f"CSV file for {pool_name} is empty. No visualization generated.")
            return

        # Convert timestamp to datetime
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])

        # Filter to only include the last 7 days
        cutoff_date = datetime.now() - timedelta(days=7)
        filtered_df = df[df['Timestamp'] >= cutoff_date]

        # If no data in the last 7 days, use all data (for now)
        if filtered_df.empty:
            logging.info(f"No data in the last 7 days for {pool_name}, using all available data")
            filtered_df = df

        # Create the plot
        plt.figure(figsize=(12, 6))

        # Get closed periods for shading
        start_date = filtered_df['Timestamp'].min().date()
        end_date = filtered_df['Timestamp'].max().date()

        try:
            closed_periods = opening_hours.get_closed_periods(pool_name, start_date, end_date)

            # Add shaded regions for closed periods
            ax = plt.gca()
            for start, end in closed_periods:
                # Create a rectangle patch for the closed period
                width = (end - start).total_seconds() / 3600 / 24  # width in days
                rect = Rectangle(
                    (mdates.date2num(start), 0),  # bottom left point
                    width,  # width in days
                    1000000,  # very tall to cover any y value
                    facecolor='lightgray',
                    alpha=0.5,
                    edgecolor='none',
                    zorder=0  # ensure it's behind the data points
                )
                ax.add_patch(rect)

            logging.info(f"Added {len(closed_periods)} closed period shading for {pool_name}")
        except Exception as e:
            logging.warning(f"Could not add closed period shading for {pool_name}: {e}")

        if pool_name == "Hallenbad Oerlikon":
            ax = plt.gca()

            # Get x-axis limits in date format
            latest_time = datetime.now()
            earliest_time = latest_time - timedelta(days=7)
            x_min = mdates.date2num(earliest_time)
            x_max = mdates.date2num(latest_time)
            x_width = x_max - x_min

            # Add very faint green shading for low occupancy (0-80)
            rect_low = Rectangle(
                (x_min, 0),  # bottom left point
                x_width,     # full width of the plot
                80,          # height up to 80
                facecolor='green',
                alpha=0.04,   # very faint
                edgecolor='none',
                zorder=0.5   # above closed periods but below data points
            )
            ax.add_patch(rect_low)

            # Add very faint yellow shading for medium occupancy (80-120)
            rect_medium = Rectangle(
                (x_min, 80),  # bottom left point
                x_width,      # full width
                40,           # height from 80 to 120
                facecolor='yellow',
                alpha=0.04,    # very faint
                edgecolor='none',
                zorder=0.5
            )
            ax.add_patch(rect_medium)

            # Add very faint red shading for high occupancy (120+)
            rect_high = Rectangle(
                (x_min, 120),  # bottom left point
                x_width,       # full width
                1000000,       # very tall to cover all higher values
                facecolor='red',
                alpha=0.06,     # very faint
                edgecolor='none',
                zorder=0.5
            )
            ax.add_patch(rect_high)

            # Add legend entries for occupancy levels
            plt.plot([], [], color='green', alpha=0.3, linewidth=10, label='Low occupancy (< 80)')
            plt.plot([], [], color='yellow', alpha=0.3, linewidth=10, label='Medium occupancy (80-120)')
            plt.plot([], [], color='red', alpha=0.3, linewidth=10, label='High occupancy (> 120)')

        # Plot the guest count data
        plt.plot(filtered_df['Timestamp'],
                 filtered_df['Number of Guests'],
                 marker='o', linestyle='-',
                 color='#3498db', zorder=2)

        # Set title and labels
        plt.title(f"Guest Count - {pool_name}", fontsize=16)
        plt.ylabel("Number of Guests", fontsize=12)

        # Format x-axis
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M %a %d.%m.%Y'))
        plt.xticks(rotation=45)

        # Set y-axis to only show integers (no half-guests)
        ax = plt.gca()
        ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))

        # Dynamically set y-axis limits based on data
        min_val = filtered_df['Number of Guests'].min()
        max_val = filtered_df['Number of Guests'].max()
        lower_limit = max(0, min_val - 2)  # Don't go below 0
        upper_limit = max_val + 2
        plt.ylim(lower_limit, upper_limit)

        # Set fixed 7-day time range for x-axis
        latest_time = datetime.now()
        earliest_time = latest_time - timedelta(days=7)
        plt.xlim(earliest_time, latest_time)

        # Add grid
        plt.grid(True, alpha=0.3)

        # Add legend for closed periods
        if pool_name == "Hallenbad Oerlikon":
            plt.plot([], [], color='lightgray', alpha=0.5, linewidth=10, label='Pool closed for public')
            plt.legend(loc='upper right')
        else:
            # Original legend for other pools
            plt.plot([], [], color='lightgray', alpha=0.5, linewidth=10, label='Pool closed for public')
            plt.legend(loc='upper right')

        # Tight layout to ensure everything fits
        plt.tight_layout()

        # Save the plot
        plt.savefig(img_file, dpi=100)
        plt.close()

        logging.info(f"Visualization for {pool_name} saved to {img_file}")

    except Exception as e:
        logging.error(f"Error generating visualization for {pool_name}: {e}")


def generate_all_visualizations():
    """Generate visualizations for all pools"""
    for pool_name, _ in pool_mapping:
        generate_visualization(pool_name)


# Main function with interval parameter for flexibility
def main(interval_minutes=10, run_once=False):
    logging.info("Starting pool guest count scraper for multiple pools...")

    # Run immediately first time
    scrape_guest_counts()

    # Generate visualizations after scraping
    generate_all_visualizations()

    # If run_once is True, exit after first run
    if run_once:
        return

    # Then run every X minutes
    interval_seconds = interval_minutes * 60
    while True:
        logging.info(f"Sleeping for {interval_minutes} minutes...")
        # Sleep for the specified interval
        time.sleep(interval_seconds)
        scrape_guest_counts()
        # Generate visualizations after each scrape
        generate_all_visualizations()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Scrape pool guest count data for multiple pools')
    parser.add_argument('--interval', type=int, default=10, help='Interval in minutes between scrapes')
    parser.add_argument('--once', action='store_true', help='Run only once and exit')
    parser.add_argument('--visualize-only', action='store_true', help='Only generate visualizations from existing data')

    args = parser.parse_args()

    if args.visualize_only:
        generate_all_visualizations()
    else:
        main(interval_minutes=args.interval, run_once=args.once)
