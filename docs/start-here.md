# Start here: what are we building, and why?

You do not need to know InfluxData products to read this guide. Some Linux
terminal and Kubernetes familiarity will help when you get to installation.
If you do not yet have a working Kubernetes cluster, stop at the prerequisite
checklist and build that foundation first. This repository does not install
Kubernetes itself.

## The 60-second explanation

**InfluxData** is the company behind **InfluxDB**, a database used for data that
changes over time: temperatures, machine measurements, application metrics and
similar timestamped observations. That is usually called **time-series data**.

**InfluxDB Clustered** is the distributed, self-managed product covered here.
Instead of one database process doing everything, several cooperating services
handle incoming writes, queries and storage. Kubernetes runs those services.

This lab supplies the pieces around the database too:

- **SeaweedFS** supplies an S3-compatible place to store persisted data files.
- **PostgreSQL** supplies a database for catalog and management metadata.
- **Grafana** displays dashboards so you can see what is happening.
- **Telegraf** collects measurements from your machines and sends them to InfluxDB.

The result is a learning environment, not a miniature production guarantee.

## First decision: is this the right InfluxDB guide?

InfluxDB product names matter. **Clustered is not the same installation as the
standalone InfluxDB 3 Core or InfluxDB 3 Enterprise server.** Their commands,
ports and configuration are not interchangeable.

Use this repository if you specifically want to learn the distributed
**Clustered** deployment and can obtain its license and registry access from
InfluxData. This is not a free, anonymous download of every required component.
Downloading this GitHub repository or its public Helm chart does not grant
access to the licensed package or images.

If you do not have those inputs yet, you can still read the architecture and
practice the SeaweedFS section separately. Do not invent a license, borrow a
registry credential or substitute a different InfluxDB product silently.
For product selection, start with the [official documentation](https://docs.influxdata.com/).

## A simple mental model

Think of a small library:

| Piece | Its job in this lab | Library analogy |
|---|---|---|
| Router | Accepts incoming measurements and forwards them | Reception desk |
| Ingester | Receives writes and buffers recent data | Intake workbench |
| Querier | Answers database queries | Research desk |
| Catalog services | Coordinate metadata about the stored data | Catalog desk |
| PostgreSQL | Stores catalog/management metadata | Catalog records |
| SeaweedFS/S3 | Stores persisted object files such as Parquet | Shelves holding the books |
| Compactor | Reorganizes stored data files for efficient use | Staff reorganizing shelves |
| Kubernetes | Keeps the component workloads running | Building operations |

This is only a learning analogy; use the official architecture documentation
for detailed consistency, durability and replication behavior.

A successful write/query test is one checkpoint. It does not establish backup
safety, high availability, or how much traffic the system can handle.

## Where the data goes

1. A client sends timestamped measurements to Clustered using a **write API**.
2. The router and ingestion services handle those writes. Recent data and the
   ingester's write-ahead log are not the same thing as persisted object files.
3. Persisted data is stored in object storage, backed by SeaweedFS in this lab.
4. Catalog metadata helps Clustered locate and interpret stored data.
5. A query client asks for data, and the querier returns the results.

PostgreSQL and SeaweedFS therefore have different jobs. Do not choose one
instead of the other, and do not delete either one's persistent storage when
troubleshooting an unrelated dashboard.

## Why SeaweedFS is here

Clustered needs object storage. **S3-compatible** means that software can use the
S3 API to talk to that storage service. In this lab SeaweedFS provides that API
locally. An AWS account is not needed for this local SeaweedFS recipe; tools
named `aws` or `boto3` can also talk to a compatible local endpoint.

A **bucket** is a named container for objects. We create an object-store bucket
named `lab`. SeaweedFS stores the bytes and metadata on persistent Kubernetes
volumes, so merely closing a terminal does not delete them.

Persistent does not mean safe from disk or node failure. This recipe uses one
copy of the object data and local disks; it has no demonstrated disaster-recovery
or automatic storage-failover design.

Two uses of the word “bucket” can be confusing:

- SeaweedFS bucket `lab`: the object-store container used by Clustered internally.
- The v2-compatible write API's `bucket=telegraf` parameter: selects the InfluxDB
  **database** named `telegraf`. It is not the SeaweedFS object-store bucket.

## What the two kinds of dashboards show

**Bundled operational dashboards** ask Prometheus for internal service metrics.
They help answer “Is the router receiving writes?” or “Are components healthy?”
They do not automatically query every measurement stored in your database.

**The Telegraf dashboard** asks InfluxDB for measurements collected from the lab
nodes, such as CPU use and available memory. It uses a separate read-only
InfluxDB datasource. Installing Grafana alone does not install this collector.

The screenshots in this repository show a working lab. They are examples of
what the views can look like, not numbers your machines must reproduce.

## Read the installation as a sequence of checkpoints

| Stage | What you do | Evidence before you continue |
|---|---|---|
| 1. Prerequisites | Check Kubernetes, compatible nodes, tools and product access | Correct cluster selected, enough eligible nodes, working storage class, your own license and registry inputs |
| 2. SeaweedFS | Install persistent storage components, enable S3 authentication, create `lab` | Pods ready, PVCs Bound, signed upload/download/delete succeeds |
| 3. PostgreSQL | Generate private credentials and deploy its persistent workload | Real SQL connection succeeds; readiness is not the only check |
| 4. Clustered | Configure storage references and install the package | Actual application workloads ready, including three catalog peers |
| 5. First data | Create a small database and scoped token; write/query two test points | SQL returns the expected two fixture rows |
| 6. Grafana | Render authorized dashboards, add authentication and persistence | Login works; Prometheus datasource is healthy |
| 7. Telegraf | Collect node metrics and import their dashboard | Recent measurements arrive from each intended node |

Follow [prerequisites](prerequisites.md), then [SeaweedFS](seaweedfs.md), then
[Clustered](clustered.md), then [Grafana and Telegraf](grafana.md). Return to
[troubleshooting](troubleshooting.md) at the first failed checkpoint instead of
continuing with an incomplete foundation.

The initial Clustered test uses a localhost-only port-forward for safer access.
The monitoring chapter explicitly explains the later optional LAN/TLS setup,
because a collector pod cannot reach your laptop's `localhost`.

## How to use the commands safely

- Run commands from the repository root unless a section says otherwise.
- A **read-only** command inspects the current state. A command marked **changes
  cluster state** creates or updates something in Kubernetes or the database.
- Replace your own hostnames/context/node choices where prompted. An example
  name ending in `.example` is not a real hostname that will resolve for you.
- Keep related commands in the same Bash shell: variables such as `$LOCAL` and
  `$SEAWEEDFS_CHART` do not automatically exist in a newly opened terminal.
- A port-forward needs its own terminal and keeps running until you stop it.
- Never switch off certificate verification just to get past a TLS error.
- Private inputs go into ignored, restricted directories, not public YAML.
- Stop when a command fails. Do not “fix” authentication by deleting data or
  recreating passwords over an initialized database.
- Read the expected result as a checkpoint, not as a claim that a command was
  already run on your machines.

There is no destructive cleanup shortcut here. Deleting a namespace or volume
can remove the only copy of data you wanted to keep.

## Small glossary

| Term | Plain-English meaning here |
|---|---|
| Node | A machine or VM participating in Kubernetes |
| Pod | Kubernetes' smallest running workload unit; contains one or more containers |
| Namespace | A named grouping of Kubernetes resources, not a security boundary by itself |
| Container image | The packaged software Kubernetes downloads and runs |
| Registry | A server that distributes images or the licensed package |
| Helm chart | A configurable Kubernetes installation package |
| Helm release | One installation of a chart, with a particular name and configuration |
| Values file | YAML settings supplied to a Helm chart |
| Operator / kubit | A controller that turns Clustered's desired configuration into running resources |
| AppInstance | The desired Clustered application configuration managed by that operator |
| Service | A stable network entry point for a group of Kubernetes pods |
| Endpoint | The hostname/address and port at which a client reaches a service |
| ClusterIP | An internal Kubernetes Service address; not normally reachable directly from your laptop |
| NodePort | A Service exposed on a chosen port of the Kubernetes nodes |
| Port-forward | A temporary connection from your workstation to an internal Service |
| PVC / persistent volume claim | A workload's request for storage that survives pod replacement |
| StorageClass | The policy/provisioner Kubernetes uses to supply that storage |
| Secret | Kubernetes resource for sensitive configuration; base64 alone is not encryption |
| Token | A credential granting specific API permissions; management and data tokens differ |
| TLS / CA | Encryption and certificate trust used to verify the service you are contacting |
| WAL | Write-ahead log: the ingester's local log of writes, not an off-cluster backup |
| Parquet | A column-oriented file format used for persisted data |
| Replica | Another instance of a component; not automatically another safe copy of all data |
| Datasource | Grafana's connection settings for the system supplying a panel's data |

Continue with [the prerequisite checklist](prerequisites.md).
