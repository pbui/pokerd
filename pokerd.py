#!/usr/bin/env python3

''' pokerd.py - Simple Poker Server Daemon


'''

import asyncio
import dataclasses
import enum
import logging
import random

# Constants

POKERD_HOST = '0.0.0.0'
POKERD_PORT = 9204

HEARTS      = chr(9829) # Character 9829 is '♥'.
DIAMONDS    = chr(9830) # Character 9830 is '♦'.
SPADES      = chr(9824) # Character 9824 is '♠'.
CLUBS       = chr(9827) # Character 9827 is '♣'.

# Classes

class PokerDealerState(enum.Enum):
    WAITING   = 0
    SHUFFLING = 1
    DEALING   = 2
    FLOP      = 3
    TURN      = 4
    RIVER     = 5

class PokerCard:
    RANK = {
        11: 'J',
        12: 'Q',
        13: 'K',
        14: 'A',
    }
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank

    def __str__(self):
        return f'[{PokerCard.RANK.get(self.rank, self.rank)}{self.suit}]'

class PokerDeck:
    def __init__(self):
        self.shuffle()

    def shuffle(self):
        self.cards = []
        for suit in (HEARTS, DIAMONDS, SPADES, CLUBS):
            for rank in range(2, 15):
                self.cards.append(PokerCard(suit, rank))
        random.shuffle(self.cards)

    def deal(self):
        return self.cards.pop()

class PokerDealer:
    def __init__(self, host=POKERD_HOST, port=POKERD_PORT):
        self.host    = host
        self.port    = port
        self.state   = PokerDealerState.WAITING
        self.players = 0
        self.deck    = PokerDeck()

    async def run(self):
        self.server = await asyncio.start_server(
            PokerPlayer.make_client_handler(self),
            self.host,
            self.port
        )

        addresses = ', '.join(':'.join(map(str, s.getsockname())) for s in self.server.sockets)
        logging.info('Serving on %s', addresses)

        async with self.server:
            await self.server.serve_forever()

class PokerPlayer:
    def __init__(self, dealer):
        self.dealer = dealer

    async def handle_client(self, reader, writer):
        dealer = self.dealer
        keep_playing = True

        address = ':'.join(map(str, writer.get_extra_info('peername')))
        logging.info('Player %s connected!', address)

        while keep_playing:
            # 1. Check if game is already in progress
            while dealer.state != PokerDealerState.WAITING:
                writer.write('\rWaiting for next round...'.encode())
                await writer.drain()
                await asyncio.sleep(1)

            # 2. Check if we have enough players (> 1)
            dealer.players += 1
            while dealer.players < 2:
                writer.write('\rWaiting for more players...'.encode())
                await writer.drain()
                await asyncio.sleep(1)

            writer.write(f'\nThere are now {dealer.players} players\n'.encode())
            await writer.drain()

            # 3. Have dealer shuffle
            if dealer.state == PokerDealerState.WAITING:
                dealer.deck.shuffle()
                dealer.state = PokerDealerState.DEALING

            # 4. Get cards
            hand = []
            while len(hand) < 2:
                writer.write('\rReceiving hand...'.encode())
                await writer.drain()

                hand.append(dealer.deck.deal())
                await asyncio.sleep(1)

            writer.write(f'\nYour cards: {", ".join(map(str, hand))}\n'.encode())
            await writer.drain()

            dealer.players -= 1
            keep_playing = False

        dealer.state = PokerDealerState.WAITING
        writer.close()

    @staticmethod
    def make_client_handler(dealer):
        poker_player = PokerPlayer(dealer)
        return poker_player.handle_client

# Functions

# Main Execution

async def main():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    dealer = PokerDealer()
    await dealer.run()

if __name__ == '__main__':
    asyncio.run(main())
