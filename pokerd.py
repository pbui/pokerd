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
    WAITING   = enum.auto()
    SHUFFLING = enum.auto()
    DEALING   = enum.auto()
    FLOP      = enum.auto()
    BET1      = enum.auto()
    TURN      = enum.auto()
    RIVER     = enum.auto()

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
        self.players = []
        self.deck    = PokerDeck()
        self.table   = []

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

    def __init__(self, address):
        self.hand    = []
        self.address = address

    @staticmethod
    async def handle_client(dealer, reader, writer):
        player = PokerPlayer(':'.join(map(str, writer.get_extra_info('peername'))))
        logging.info('Player %s connected!', player.address)

        try:
            keep_playing = True

            while keep_playing:
                # 1. Check if game is already in progress
                while dealer.state != PokerDealerState.WAITING:
                    writer.write('\r[W] Waiting for next round...'.encode())
                    await writer.drain()
                    await asyncio.sleep(1)

                # 2. Check if we have enough players (> 1)
                dealer.players.append(player)
                while len(dealer.players) < 2:
                    writer.write('\r[W] Waiting for more players...'.encode())
                    await writer.drain()
                    await asyncio.sleep(1)

                writer.write(f'\n[W] There are now {len(dealer.players)} players\n'.encode())
                await writer.drain()

                # 3. Have dealer shuffle
                if dealer.state == PokerDealerState.WAITING:
                    dealer.deck.shuffle()
                    dealer.state = PokerDealerState.DEALING

                # 4. Get cards
                while len(player.hand) < 2:
                    writer.write('\r[D] Receiving hand...'.encode())
                    await writer.drain()

                    player.hand.append(dealer.deck.deal())
                    await asyncio.sleep(1)

                writer.write(f'\n[D] Your cards: {", ".join(map(str, player.hand))}\n'.encode())
                await writer.drain()

                # 5. Get flop
                if dealer.state == PokerDealerState.DEALING:
                    writer.write('\n[F] Burning...'.encode())
                    burn = dealer.deck.deal()

                    writer.write('\n[F] Dealing Flop...'.encode())
                    dealer.table = [dealer.deck.deal() for _ in range(3)]
                    dealer.state = PokerDealerState.FLOP
                    dealer.ready = 0

                writer.write(f'\n[F] Table cards: {", ".join(map(str, dealer.table))}\n'.encode())
                await writer.drain()

                # 6. Fold or not?
                response = None
                while not response:
                    writer.write('\n[B] (F)old or (S)tand? '.encode())
                    await writer.drain()
                    response = (await reader.readline()).decode().strip().lower()

                if response == 'f':
                    raise ConnectionResetError

                dealer.ready += 1

                # 7. Wait for other players
                while dealer.ready < len(dealer.players):
                    writer.write('\r[B] Waiting for other players...? '.encode())
                    await writer.drain()
                    await asyncio.sleep(1)

                # X. Place holder
                logging.info('Show all cards')
                for other in dealer.players:
                    if player == other:
                        continue

                    writer.write(f'\n[X] Player {other.address} has: {", ".join(map(str, other.hand))}'.encode())
                    await writer.drain()

                writer.write(f'\n[X] Round Over!\n'.encode())
                await writer.drain()
                await asyncio.sleep(5)

                dealer.players.remove(player)
                dealer.state = PokerDealerState.WAITING
        except ConnectionResetError:
            pass
        finally:
            dealer.players.remove(player)
            dealer.state = PokerDealerState.WAITING
            writer.close()

    @staticmethod
    def make_client_handler(dealer):
        return lambda writer, reader: PokerPlayer.handle_client(dealer, writer, reader)

# Functions

# Main Execution

async def main():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    dealer = PokerDealer()
    await dealer.run()

if __name__ == '__main__':
    asyncio.run(main())
