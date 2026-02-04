import pandas as pd
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI_LOCAL")
USERNAME = os.getenv("NEO4J_USERNAME_LOCAL")
PASSWORD = os.getenv("NEO4J_PASSWORD_LOCAL")
DATABASE = os.getenv("NEO4J_DATABASE_LOCAL")


# Read the CSV (note the delimiter is ';')
df = pd.read_csv("../../data/raumbelegung.csv", sep=';')

# Function to safely combine date and time, handling '24:00' and missing values
def fix_time(date_val, time_val):
    if pd.isna(date_val) or pd.isna(time_val):
        return pd.NaT
    date_str = str(date_val)
    time_str = str(time_val)

    if time_str == '24:00':
        # Move to next day at 00:00
        new_date = pd.to_datetime(date_str, format='%Y-%m-%d') + pd.Timedelta(days=1)
        return pd.Timestamp(new_date.year, new_date.month, new_date.day, 0, 0)
    else:
        return pd.to_datetime(date_str + ' ' + time_str, format='%Y-%m-%d %H:%M')

# Create start and end datetime columns
df['start'] = df.apply(lambda row: fix_time(row['begindat'], row['beginn']), axis=1)
df['end'] = df.apply(lambda row: fix_time(row['endedat'], row['ende']), axis=1)

# Keep only the relevant columns
df_clean = df[['titel', 'raum', 'gebaeude', 'start', 'end']]
df_clean = df_clean.dropna(subset=['start', 'end'])

print(df_clean)

driver = GraphDatabase.driver(NEO4J_URI, auth=(USERNAME, PASSWORD))

def clear_database(tx):
    tx.run("MATCH (n) DETACH DELETE n")


def create_graph_from_dataframe(tx, row):
    query = """
 // Create or match Building
    MERGE (b:Building {name: $gebaeude})

    // Create or match Room inside the building
    MERGE (r:Room {name: $raum})
    MERGE (r)-[:LOCATED_IN]->(b)
    MERGE (b)-[:HAS_ROOM]->(r)  // backward connection

    // Create or match Event
    MERGE (e:Event {name: $titel, start: datetime($start)})
    SET e.end = datetime($end)

    // Connect Event to Room
    MERGE (e)-[:HELD_IN]->(r)
    MERGE (r)-[:HAS_EVENT]->(e)  // backward connection
    """
    tx.run(query,
           titel=row['titel'],
           raum=row['raum'],
           gebaeude=row['gebaeude'],
           start=row['start'],
           end=row['end'])

# --- Use the df_clean DataFrame directly ---
with driver.session(database=DATABASE) as session:
    session.execute_write(clear_database) #Reset Database for new dynamic data

    for _, row in df_clean.iterrows():
        session.execute_write(create_graph_from_dataframe, row)

driver.close()
print("Graph successfully created from DataFrame!")
