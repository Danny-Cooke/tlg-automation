"""The salon's client list, mirrored from Fresha into DynamoDB, and the
opt-out link that goes in every marketing text (plan job 10).

    clients.sync          Lambda: page through Fresha's clients, mirror them
    clients.unsubscribe   Lambda: the /stop/<token> page behind the stop link
    clients.store         the DynamoDB table, one row per Fresha client
    clients.model         the row, and how Fresha's record becomes one
"""
