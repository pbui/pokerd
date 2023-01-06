#!/usr/bin/env python3

''' pokerd.py - Simple Poker Server Daemon


'''

import asyncio
import collections
import dataclasses
import enum
import logging
import random

# Constants

POKERD_HOST     = '0.0.0.0'
POKERD_PORT     = 9204
POKERD_VERSION  = '0.0.1'

HEARTS          = chr(9829) # Character 9829 is '♥'
DIAMONDS        = chr(9830) # Character 9830 is '♦'
SPADES          = chr(9824) # Character 9824 is '♠'
CLUBS           = chr(9827) # Character 9827 is '♣'

# Classes

class PokerState(enum.Enum):
    LOBBY = enum.auto()
    TABLE = enum.auto()

    DEAL  = enum.auto()
    FLOP  = enum.auto()
    BETF  = enum.auto()
    TURN  = enum.auto()
    RIVER = enum.auto()

    FOLD  = enum.auto()
    QUIT  = enum.auto()


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
        return f'[{PokerCard.RANK.get(self.rank, self.rank):<2}{self.suit}]'


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
    BANNER = f'''Welcome to Poker Daemon {POKERD_VERSION}
                 _                _
     _ __   ___ | | _____ _ __ __| |
    | '_ \ / _ \| |/ / _ \ '__/ _` |
    | |_) | (_) |   <  __/ | | (_| |
    | .__/ \___/|_|\_\___|_|  \__,_|
    |_|
    '''
    MINIMUM_PLAYERS = 2

    def __init__(self, host=POKERD_HOST, port=POKERD_PORT):
        self.host    = host
        self.port    = port
        self.state   = PokerState.LOBBY
        self.players = []
        self.deck    = PokerDeck()
        self.table   = []

    def add_player(self, player):
        self.players.append(player)
        logging.info('Now have %d players', len(self.players))

        if len(self.players) < PokerDealer.MINIMUM_PLAYERS:
            self.state = PokerState.TABLE
        else:
            self.state = PokerState.DEAL
            for player in self.players:
                player.hand = []
            self.deck.shuffle()

    def remove_player(self, player):
        self.players.remove(player)
        logging.info('Now have %d players', len(self.players))
        if not self.players:
            self.state = PokerState.LOBBY

    def deal(self):
        return self.deck.deal()

    async def deal_hands(self):
        if self.state == PokerState.DEAL:
            self.state = PokerState.FLOP
            for i in range(1, 3):
                for player in self.players:
                    player.hand.append(self.deal())

    async def deal_flop(self):
        if self.state == PokerState.FLOP:
            self.deal()
            self.state = PokerState.TURN
            self.table = [self.deal() for _ in range(3)]

    async def reset(self):
        if self.state != PokerState.LOBBY:
            self.state   = PokerState.LOBBY
            self.players = []

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

    def __init__(self, dealer, reader, writer):
        self.hand    = []
        self.dealer  = dealer
        self.reader  = reader
        self.writer  = writer
        self.state   = PokerState.LOBBY
        self.address = ':'.join(map(str, writer.get_extra_info('peername')))

    # I/O Methods

    async def write_lines(self, lines, overwrite=False):
        for line in lines.split('\n'):
            prefix = '\r' if overwrite else '\n'
            self.writer.write(f'{prefix}{line}'.encode())
        await self.writer.drain()

    async def read_response(self, prompt):
        response = None
        while not response:
            await self.write_lines(f'\n{prompt}? ')
            response = (await self.reader.readline()).decode().strip().lower()
        return response

    # Player Methods

    async def display_banner(self):
        await self.write_lines(self.dealer.BANNER)

    async def wait_in_lobby(self):
        await self.write_lines('\nWaiting in lobby for next round...')

        seconds = 0
        while self.dealer.state not in (PokerState.LOBBY, PokerState.TABLE):
            seconds += 1
            await self.write_lines(f'Waiting in lobby for next round... {seconds}s', True)
            await asyncio.sleep(1)

        self.state = PokerState.TABLE

    async def wait_at_table(self):
        await self.write_lines('\nWaiting at table for players...')

        self.dealer.add_player(self)

        seconds = 0
        while self.dealer.state == PokerState.TABLE:
            seconds += 1
            await self.write_lines(f'Waiting at table for players... {seconds}s', True)
            await asyncio.sleep(1)

        self.state = PokerState.DEAL

        while not all(player.state == PokerState.DEAL for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\nTable has {len(self.dealer.players)} players')

    async def wait_for_hand(self):
        await self.write_lines('\nDealing hand...')
        await self.dealer.deal_hands()

        self.state = PokerState.FLOP

        while not all(player.state == PokerState.FLOP for player in self.dealer.players):
            await asyncio.sleep(1)

        await self.write_lines(f'\nYour cards: {"".join(map(str, self.hand))}')

    async def wait_for_flop(self):
        await self.write_lines('\nDealing flop...')
        await self.dealer.deal_flop()

        self.state = PokerState.BETF

        while not all(player.state == PokerState.BETF for player in self.dealer.players):
            await asyncio.sleep(1)
                
        await self.write_lines(f'\nFlop cards: {"".join(map(str, self.dealer.table))}')

    async def wait_for_call(self, next_state):
        response = await self.read_response('Choose an action: (F)old or (C)all')

        if response == 'f':
            self.state = PokerState.FOLD
            self.dealer.remove_player(self)
        else:
            self.state = next_state

            await self.write_lines('Waiting for other players...')
            seconds = 0
            while not all(player.state == next_state for player in self.dealer.players):
                await self.write_lines(f'Waiting for other players... {seconds}s', True)
                await asyncio.sleep(1)
                seconds += 1

            await self.write_lines('')
            winner_score = 0
            for player in self.dealer.players:
                player_score = score_hand(player.hand, self.dealer.table)
                winner_score = max(winner_score, player_score)
                await self.write_lines(
                    f'Player {player.address} had: {"".join(map(str, player.hand))} (Score: {player_score})'
                )

            if winner_score == score_hand(self.hand, self.dealer.table):
                await self.write_lines('\nYou are the winner!')
            else:
                await self.write_lines('\nYou lost...')

    async def wait_for_turn(self):
        self.state = PokerState.LOBBY
        await self.dealer.reset()

    # Static Methods

    @staticmethod
    async def handle_client(dealer, reader, writer):
        player = PokerPlayer(dealer, reader, writer)
        logging.info('Player %s connected!', player.address)

        await player.display_banner()

        try:
            while player.state != PokerState.QUIT:
                if   player.state == PokerState.LOBBY: await player.wait_in_lobby()
                elif player.state == PokerState.TABLE: await player.wait_at_table()
                elif player.state == PokerState.DEAL:  await player.wait_for_hand()
                elif player.state == PokerState.FLOP:  await player.wait_for_flop()
                elif player.state == PokerState.BETF:  await player.wait_for_call(PokerState.TURN)
                elif player.state == PokerState.TURN:  await player.wait_for_turn()
                elif player.state == PokerState.FOLD:  player.state = PokerState.LOBBY

                await asyncio.sleep(1)
        except ConnectionResetError:
            pass
        finally:
            player.dealer.remove_player(player)

    @staticmethod
    def make_client_handler(dealer):
        return lambda writer, reader: PokerPlayer.handle_client(dealer, writer, reader)


# Functions

def score_hand(hand, table):
    # 10. High Card (2-14)
    ranks = [c.rank for c in hand]
    score = max(ranks)

    # 9, 8, 7. Pair, Two Pair, Three of a Kind
    rank_counts = collections.Counter(c.rank for c in hand + table)
    for rank, count in sorted(rank_counts.items()):
        if rank in ranks:       # Note: disregard combos from only the table
            if count == 2:      # Pairs:            22 - 34
                if score < 20:
                    score = 20 + rank
                else:           # Two Pair:         42 - 54
                    score = 40 + rank
            elif count == 3:    # Three of kind:    62 - 74
                score = 60 + rank

    return score

# Main Execution

async def main():
    logging.basicConfig(
        format   = '[%(levelname)1.1s %(asctime)s %(module)s:%(lineno)d] %(message)s',
        datefmt  = '%Y-%m-%d %H:%M:%S',
        level    = logging.INFO,
    )

    dealer = PokerDealer()
    await dealer.run()

if __name__ == '__main__':
    asyncio.run(main())
