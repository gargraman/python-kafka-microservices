# -*- coding: utf-8 -*-
#
# Copyright 2022 Confluent Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Microservice to bake pizzas

import sys
import json
import time
import logging

from utils import (
    GracefulShutdown,
    log_ini,
    save_pid,
    log_exception,
    timestamp_now,
    delivery_report,
    get_script_name,
    get_system_config,
    validate_cli_args,
    log_event_received,
    # update_pizza_status,
    get_topic_partitions,
    set_producer_consumer,
    get_custom_partitioner,
)


####################
# Global variables #
####################
SCRIPT = get_script_name(__file__)
log_ini(SCRIPT)

# Validate command arguments
kafka_config_file, sys_config_file = validate_cli_args(SCRIPT)

# Get system config file
SYS_CONFIG = get_system_config(sys_config_file)

# Set producer/consumer objects
PRODUCE_TOPIC_BAKED = SYS_CONFIG["kafka-topics"]["pizza_baked"]
PRODUCE_TOPIC_STATUS = SYS_CONFIG["kafka-topics"]["pizza_status"]
CONSUME_TOPICS = [
    SYS_CONFIG["kafka-topics"]["pizza_assembled"],
]
_, PRODUCER, CONSUMER, ADMIN_CLIENT = set_producer_consumer(
    kafka_config_file,
    producer_extra_config={
        "on_delivery": delivery_report,
        "client.id": SYS_CONFIG["kafka-client-id"]["microservice_baked"],
    },
    consumer_extra_config={
        "group.id": SYS_CONFIG["kafka-consumer-group-id"]["microservice_baked"],
        "client.id": SYS_CONFIG["kafka-client-id"]["microservice_baked"],
    },
)
CUSTOM_PARTITIONER = get_custom_partitioner()
PARTITIONS_BAKED = get_topic_partitions(ADMIN_CLIENT, PRODUCE_TOPIC_BAKED)
PARTITIONS_STATUS = get_topic_partitions(ADMIN_CLIENT, PRODUCE_TOPIC_STATUS)

# Set signal handler
GRACEFUL_SHUTDOWN = GracefulShutdown(consumer=CONSUMER)


#####################
# General functions #
#####################
def pizza_baked(order_id: str):
    # Produce to kafka topic
    PRODUCER.produce(
        PRODUCE_TOPIC_BAKED,
        key=order_id,
        value=json.dumps(
            {
                "status": SYS_CONFIG["status-id"]["pizza_baked"],
                "timestamp": timestamp_now(),
            }
        ).encode(),
        partition=CUSTOM_PARTITIONER(order_id.encode(), PARTITIONS_BAKED),
    )
    PRODUCER.flush()


def receive_pizza_assembled():
    CONSUMER.subscribe(CONSUME_TOPICS)
    logging.info(f"Subscribed to topic(s): {', '.join(CONSUME_TOPICS)}")
    while True:
        with GRACEFUL_SHUTDOWN as _:
            event = CONSUMER.poll(1)
            if event is not None:
                if event.error():
                    logging.error(event.error())
                else:
                    try:
                        log_event_received(event)

                        order_id = event.key().decode()
                        try:
                            baking_time = json.loads(event.value().decode()).get(
                                "baking_time", 0
                            )
                        except Exception:
                            log_exception(
                                f"Error when processing event.value() {event.value()}",
                                sys.exc_info(),
                            )
                        else:
                            # Assemble pizza (blocking point as it is not using asyncio, but that is for demo purposes)
                            logging.info(
                                f"Preparing order '{order_id}', baking time is {baking_time} second(s)"
                            )
                            time.sleep(baking_time)
                            logging.info(f"Order '{order_id}' is baked!")

                            # Update kafka topics
                            pizza_baked(
                                order_id,
                            )
                            # update_pizza_status(
                            #     PRODUCER,
                            #     CUSTOM_PARTITIONER,
                            #     PRODUCE_TOPIC_STATUS,
                            #     PARTITIONS_BAKED,
                            #     order_id,
                            #     SYS_CONFIG["status-id"]["pizza_baked"],
                            # )

                    except Exception:
                        log_exception(
                            f"Error when processing event.key() {event.key()}",
                            sys.exc_info(),
                        )

                # Manual commit
                CONSUMER.commit(asynchronous=False)


########
# Main #
########
if __name__ == "__main__":
    # Save PID
    save_pid(SCRIPT)

    # Start consumer
    receive_pizza_assembled()
