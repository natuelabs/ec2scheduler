#!/usr/bin/env python

"""This scheduler starts/stops EC2 instances using a JSON based schedule.

Usage:
  scheduler [options]
  scheduler (-h | --help)
  scheduler --version

Options:
  -c --config CONFIG     Use alternate configuration file [default: ./aws.cnf].
  -h --help              Show this screen.
  --version              Show version.
"""

from docopt import docopt
from ConfigParser import SafeConfigParser
import boto.ec2
import boto.ec2.elb
import sys, os, json, datetime, time
from pytz import timezone

config = SafeConfigParser()
ec2_conn = {}
elb_conn = {}

def utcnow():
    return datetime.datetime.now(tz=timezone('America/Sao_Paulo'))

def run(args):
  """ Run the script

      Args:
        args: CLI arguments.
  """
  config.read([args['--config'], 'aws.conf'])

  init(args)

  while True:
    schedule()
    time.sleep(3600)

def init(args):
  """ Setup initial configuration and connections

  Args:
    args: CLI arguments.
  """

  for region in config.sections():
    if region == 'schedule':
      continue

    connection = connect_from_conf(region)
    ec2_conn[region] = connection['ec2']
    elb_conn[region] = connection['elb']
 
  global schedules
  schedules = get_schedules()

def connect_from_conf(aws_region):
  """ Connect to ec2 and elb region

    Args:
      aws_conf: aws credentials

    Returns:
      Dict with ec2 and elb connection object for region
  """
  aws_access_key = config.get(aws_region,'access_key','')
  aws_secret_key = config.get(aws_region,'secret_key','')

  return {
    'ec2':
      boto.ec2.connect_to_region(
      region_name = aws_region,
      aws_access_key_id = aws_access_key,
      aws_secret_access_key = aws_secret_key),
    'elb':
      boto.ec2.elb.connect_to_region(
      region_name = aws_region,
      aws_access_key_id = aws_access_key,
      aws_secret_access_key = aws_secret_key)
  }

def get_schedules():
  """ Read schedule configuration from file and load the json.

      Returns:
        Dict with the configuration
  """
  path = config.get('schedule', 'paths', './schedule.json')
  with open(path) as schedule_file:
    return json.load(schedule_file)

def schedule():
  """ Check all schedule configurations to start and stop instances """
  for profile in schedules['profiles']:
    print profile['name']
    instances = _get_instances(profile['instance_tags'], profile['region'])
    start_stop_instances(instances, profile['schedule'])
    reregister_elb_instances(profile)

def _get_instances(instance_tags, region):
  """ Get boto ec2 instance objects by provided tags

      Args:
        instance_tags: the tags associated with the instances
        region: aws region

      Returns:
        An array of boto ec2 instance objects
  """
  return ec2_conn[region].get_all_instances(filters={"tag:Name": instance_tags})

def start_stop_instances(instances, schedule):
  """ Start and stop the instances given a schedule

      Args:
        instances: An array of reservations containing.
        schedule: key value with days and start/stop time.
  """
  for reservation in instances:
    for instance in reservation.instances:
      region = instance.placement
      
      print utcnow().isoformat() + " " + instance.id + " " + instance.state

      if instance.state == 'running' and _get_desired_state(schedule) == 'stop':
        print utcnow().isoformat() + " Should stop " + instance.id + "."
        instance.stop()
      elif instance.state == 'stopped' and _get_desired_state(schedule) == 'start':
        print utcnow().isoformat() + " Should start " + instance.id + "."
        instance.start()
      else:
        print utcnow().isoformat() + " Nothing to do."

def _get_desired_state(schedule):
  """ Find the desired state give a schedule

      Args:
        schedule: dict with days and start/stop time.

      Returns:
        A string with the desired state. (start/stop)
  """
  current_hour = utcnow().hour
  current_week_day = time.strftime("%A", utcnow().timetuple()).lower()

  start = schedule[current_week_day]['start']
  stop = schedule[current_week_day]['stop']

  state = 'stop'
  if current_hour >= start and current_hour < stop:
    state = 'start'

  return state

def reregister_elb_instances(profile):
  """ ELB does not send health checks after stopping/starting
      the instance. This method reregister the instances in the
      profile ELB's to start sending health checks again.

      Args:
        profile: dict with profile configuration.
  """
  if 'elb_names' in profile:
    conn = elb_conn[profile['region']]
    elbs = conn.get_all_load_balancers(profile['elb_names'])
    for elb in elbs:
      instance_ids = _get_instance_ids(elb.instances)
      print "Reregistering " + elb.name + " instances."
      try:
        conn.deregister_instances(elb.name, instance_ids)
        conn.register_instances(elb.name, instance_ids)
      except Exception, e:
        print elb.name + "has no instances."
      # to avoid elb rate limit throttling
      time.sleep(1)

def _get_instance_ids(instances):
  """ Given an array of boto.ec2.instances returns
      instance ids.

      Args:
        instances: boto.ec2.instances

      Returns:
        Array of string instance ids
  """
  instance_ids = []
  for instance in instances:
    instance_ids.append(instance.id)
  return instance_ids

def run_cli():
  args = docopt(__doc__, version='scheduler 1.0')
  # We have valid args, so run the program.
  run(args)

if __name__ == "__main__":
  args = docopt(__doc__, version='scheduler 1.0')
  # We have valid args, so run the program.
  run(args)
