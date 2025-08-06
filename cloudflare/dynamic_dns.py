#!/usr/bin/python3
"""
DynDNS-style dynamic record using Cloudflare and OpenDNS

# Usage
Create a Cloudflare API key with 'edit zone' permissions
Add CLOUDFLARE_API_TOKEN to .env
Set target_zone to the root domain to manage
Set managed_name to the record you want to maintain
Run:
  python3 ./dynamic_dns.py
"""
import csv
import os
import dns.resolver
from CloudFlare import CloudFlare
from datetime import datetime
from dotenv import load_dotenv

# Load environment
load_dotenv()
# Get public IP address from OpenDNS
resolver = dns.resolver.Resolver(configure=False)
resolver.nameservers = ['208.67.222.222']
my_ip = resolver.resolve('myip.opendns.com', 'A')
public_ip = my_ip[0].to_text()
target_zone = 'somepublicdomain.com'
managed_name = f'home.{target_zone}'
log_file = f'/var/log/cloudflare_{managed_name}.log'
log_file_is_new = not os.path.exists(log_file)
print(f'Public IP: {public_ip}')
print(f'Managed record: {managed_name}')
client = CloudFlare(token=os.environ.get('CLOUDFLARE_API_TOKEN'))

# Find the zone ID
zone_id = None
for zone in client.zones.get():
  if zone['name'] == target_zone:
    zone_id = zone['id']
    break
if not zone_id:
  raise RuntimeError(f'Zone {target_zone} not found')

# Try to find the existing DNS record
dns_record = None
params = {'name': managed_name, 'type': 'A'}
records = client.zones.dns_records.get(zone_id, params=params)
if records:
  dns_record = records[0]

# Update record
if dns_record:
  record_id = dns_record['id']
  result = client.zones.dns_records.put(
    zone_id, record_id,
    data={'type': 'A', 'name': managed_name, 'content': public_ip, 'ttl': 300, 'proxied': False}
  )
  print(f'Updated record {managed_name} to {public_ip}')
else:
  result = client.zones.dns_records.post(
    zone_id,
    data={'type': 'A', 'name': managed_name, 'content': public_ip, 'ttl': 300, 'proxied': False}
  )
  print(f'Created record {managed_name} with IP {public_ip}')

# Write log file in CSV format
with open(log_file, mode='a', newline='') as f:
  writer = csv.writer(f)
  if log_file_is_new:
    writer.writerow(['timestamp', 'managed_record', 'public_ip'])

  writer.writerow([datetime.now().isoformat(), managed_name, public_ip])
