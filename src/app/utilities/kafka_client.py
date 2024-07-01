import socket
from typing import Final, Optional

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer
from confluent_kafka.admin import AdminClient, NewTopic

TOPIC_NAME: Final = "test-dev"
TOPIC_NR_OF_PARTITIONS: Final = 2
TOPIC_NR_OF_REPLICAS: Final = 2

BOOTSTRAP_SERVERS: Final = "131.154.96.188:30092,131.154.96.188:30093"
SECURITY_MECHANISM: Optional[str] = "sasl_plain"
ADMIN_USER: Final = "admin"
ADMIN_PASSWORD: Final = "pass"

"""
kafkacat -b 131.154.96.188:30092 -L \
    -X security.protocol=SASL_PLAINTEXT \
    -X sasl.mechanisms=PLAIN \
    -X sasl.username=admin \
    -X sasl.password=pass
"""

#########################################################################################################
# AdminClient

# https://github.com/confluentinc/librdkafka/blob/master/CONFIGURATION.md
conf = {"bootstrap.servers": BOOTSTRAP_SERVERS}

if SECURITY_MECHANISM == "sasl_plain":
    conf.update(
        {
            "security.protocol": "SASL_PLAINTEXT",
            "sasl.mechanism": "PLAIN",
            "sasl.username": ADMIN_USER,
            "sasl.password": ADMIN_PASSWORD,
        }
    )

admin_client = AdminClient(conf)

topic_list = []
topic_list.append(NewTopic(TOPIC_NAME, TOPIC_NR_OF_PARTITIONS, TOPIC_NR_OF_REPLICAS))
admin_client.create_topics(topic_list)


#########################################################################################################
# Producer

producer = Producer({**conf, "client.id": socket.gethostname()})


def produce_callback(err: KafkaError, msg: Message):
    if err is not None:
        print(f"Failed to deliver message: '{msg.value()}': {str(err)}")
    else:
        print(f"Message produced: key={msg.key()}, value={msg.value()}")


for idx, data in enumerate([{"key": "test-key", "value": "test-message"}] * 3):
    # Asynchronously produce a message
    producer.produce(
        TOPIC_NAME, key=data["key"], value=f"{data['value']}-{idx}".encode("utf-8"), callback=produce_callback
    )
    # Trigger `produce_callback`
    producer.poll(1)

# Deliver any outstanding messages synchronously
producer.flush()


#########################################################################################################
# Consumer


def basic_consume_loop(cons: Consumer, topics):
    try:
        cons.subscribe(topics)

        while True:
            _msg = cons.poll(timeout=1.0)
            if _msg is None:
                continue
            if _msg.error():
                if _msg.error().code() == KafkaError._PARTITION_EOF:
                    print("%% %s [%d] reached end at offset %d\n" % (_msg.topic(), _msg.partition(), _msg.offset()))
                elif _msg.error():
                    raise KafkaException(_msg.error())
            else:
                print(f"Message received: key={_msg.key()}, value={_msg.value()}")
    finally:
        # Close down consumer to commit final offsets.
        cons.close()


consumer = Consumer(
    {
        **conf,
        "group.id": "test-consumer",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
)

print("Available topics to consume: ", consumer.list_topics().topics)
basic_consume_loop(consumer, [TOPIC_NAME])
