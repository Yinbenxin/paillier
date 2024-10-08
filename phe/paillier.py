#!/usr/bin/env python3
# Portions copyright 2012 Google Inc. All Rights Reserved.
# This file has been modified by NICTA

# This file is part of pyphe.
#
# pyphe is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# pyphe is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with pyphe.  If not, see <http://www.gnu.org/licenses/>.

"""Paillier encryption library for partially homomorphic encryption."""
import pickle
import time

import libnum
import random
import os
from random import randint

import numpy as np
import torch as th

try:
    from collections.abc import Mapping
except ImportError:
    Mapping = dict

from phe.encoding import EncodedNumber, EncodedVector
from phe.util import get_random_lt_n, invert, powmod, getprimeover, isqrt, rand_int_bits, mul_mod, mod, mul, mul_mod_new

# Paillier cryptosystem is based on integer factorisation.
# The default is chosen to give a minimum of 128 bits of security.
# https://www.keylength.com/en/4/
DEFAULT_KEYSIZE = 2048

class EncryptedPublic(object):
    def __init__(self, n, nsquare, max_int, exponent=0):
        self.n = n
        self.g = n+1
        self.nsquare = nsquare
        self.max_int = max_int
        self.exponent = exponent
        self.__is_obfuscated = False

def generate_paillier_keypair(n_length=DEFAULT_KEYSIZE, precompute=True, table_path="/tmp/data/"):
    """Return a new :class:`PaillierPublicKey` and :class:`PaillierPrivateKey`.
    Add the private key to *private_keyring* if given.
    Args:
      private_keyring (PaillierPrivateKeyring): a
        :class:`PaillierPrivateKeyring` on which to store the private
        key.
      n_length: key size in bits.
    Returns:
      tuple: The generated :class:`PaillierPublicKey` and
      :class:`PaillierPrivateKey`
    """
    if os.path.exists(os.path.join(table_path, "table.pkl")):
        print(f"加载密钥。")
        with open(os.path.join(table_path, "table.pkl"), "rb") as f:
            table = pickle.load(f)
        n_length_exist = table["n_length"]
        n = table["n"]
        p = table["p"]
        q = table["q"]
        r_pow_n_l = table["r_pow_n_l"]
        if n_length_exist != n_length:
            public_key, private_key = generate_keys(n_length, precompute, table_path)
        else:
            public_key = PaillierPublicKey(n, r_pow_n_l)
            private_key = PaillierPrivateKey(public_key, p, q)
    else:
        public_key, private_key = generate_keys(n_length, precompute, table_path)
    return public_key, private_key

            
def generate_keys(n_length=DEFAULT_KEYSIZE, precompute=False, table_path="/tmp/data/"):
    """
    生成密钥。
    """
    p = q = n = None
    n_len = 0
    while n_len != n_length:
        p = getprimeover(n_length // 2)
        q = p
        while q == p:
            q = getprimeover(n_length // 2)
        n = p * q
        n_len = n.bit_length()

    if precompute:
        #print("precomputation")
        #nsquare = n*n
        psquare = p*p
        qsquare = q*q
        qsquare_inv = libnum.invmod(qsquare, psquare)

        
        from functools import partial
        import multiprocessing as mp
        try:
            import psutil
            max_processes = psutil.cpu_count(logical=False)
        except:
            max_processes = None

        pow_mod_n2_new = partial(pow_mod_n2, exp=n, n_length=n_len, psquare=psquare, qsquare=qsquare, qsquare_inv=qsquare_inv)
        r_pow_n_l = []
        pool = mp.Pool(max_processes)
        r_pow_n_l = pool.map(pow_mod_n2_new, range(16384))
        pool.close()
        pool.join()
        
        public_key = PaillierPublicKey(n, r_pow_n_l, n_length)
        table = {}
        table["n"] = n
        table["n_length"] = n_length
        table["p"] = p
        table["q"] = q
        table["r_pow_n_l"] = r_pow_n_l
        print(f"生成密钥表。")
        if not os.path.exists(table_path):
            os.makedirs(table_path)
        with open(os.path.join(table_path,"table.pkl"), "wb") as f:
            pickle.dump(table,f)
    else:
        public_key = PaillierPublicKey(n)
    private_key = PaillierPrivateKey(public_key, p, q)
    return public_key, private_key


def pow_mod_n2(base, exp, n_length, psquare, qsquare, qsquare_inv):
    if base is None:
        #base = random.SystemRandom().randrange(1, exp)
        base = rand_int_bits(n_length//3)
    x_p = powmod(base, exp, psquare)
    x_q = powmod(base, exp, qsquare)
    x = (qsquare_inv * (x_p-x_q)) % psquare
    x = x*qsquare + x_q
    return x

class PaillierPublicKey(object):
    """Contains a public key and associated encryption methods.
    Args:
      n (int): the modulus of the public key - see Paillier's paper.
    Attributes:
      g (int): part of the public key - see Paillier's paper.
      n (int): part of the public key - see Paillier's paper.
      nsquare (int): :attr:`n` ** 2, stored for frequent use.
      max_int (int): Maximum int that may safely be stored. This can be
        increased, if you are happy to redefine "safely" and lower the
        chance of detecting an integer overflow.
    """
    def __init__(self, n, r_pow_n_l=None, n_length=2048, noise=3):
        self.g = n + 1
        self.n = n
        self.nsquare = n * n
        self.max_int = n // 3 - 1
        self.r_pow_n_l = r_pow_n_l
        self.noise = noise
        self.n_length = n_length

    def __repr__(self):
        publicKeyHash = hex(hash(self))[2:]
        return "<PaillierPublicKey {}>".format(publicKeyHash[:10])

    def __eq__(self, other):
        return self.n == other.n

    def __hash__(self):
        return hash(self.n)

    def raw_encrypt(self, plaintext, r_value=None):
        """Paillier encryption of a positive integer plaintext < :attr:`n`.
        You probably should be using :meth:`encrypt` instead, because it
        handles positive and negative ints and floats.
        Args:
          plaintext (int): a positive integer < :attr:`n` to be Paillier
            encrypted. Typically this is an encoding of the actual
            number you want to encrypt.
          r_value (int): obfuscator for the ciphertext; by default (i.e.
            r_value is None), a random value is used.
        Returns:
          int: Paillier encryption of plaintext.
        Raises:
          TypeError: if plaintext is not an int.
        """
        if not isinstance(plaintext, int):
            raise TypeError('Expected int type plaintext but got: %s' %
                            type(plaintext))

        if self.n - self.max_int <= plaintext < self.n:
            # print("Very large plaintext, take a sneaky shortcut using inverses")
            neg_plaintext = self.n - plaintext  # = abs(plaintext - nsquare)
            #neg_ciphertext = (self.n * neg_plaintext + 1) % self.nsquare
            neg_ciphertext = mod(mul(self.n, neg_plaintext) + 1,self.nsquare)
            nude_ciphertext = invert(neg_ciphertext, self.nsquare)
        else:
            # we chose g = n + 1, so that we can exploit the fact that
            # (n+1)^plaintext = n*plaintext + 1 mod n^2
            nude_ciphertext = mod(mul(self.n, plaintext) + 1,self.nsquare)
            #nude_ciphertext = (self.n * plaintext + 1) % self.nsquare

        if self.r_pow_n_l:
            obfuscator = 1
            for _ in range(self.noise):
                idx = randint(1, 16383)
                #obfuscator = (obfuscator * self.r_pow_n_l[idx]) % self.nsquare
                obfuscator = mul_mod(obfuscator, self.r_pow_n_l[idx], self.nsquare)
        else:
            r = self.get_random_lt_n()
            obfuscator = powmod(r, self.n, self.nsquare)

        #return (nude_ciphertext * obfuscator) % self.nsquare
        return mul_mod(nude_ciphertext, obfuscator, self.nsquare)

    def get_random_lt_n(self):
        """Return a cryptographically random number less than :attr:`n`"""
        return random.SystemRandom().randrange(1, self.n)

    def encrypt(self, value, precision=None, r_value=None):
        """Encode and Paillier encrypt a real number *value*.
        Args:
          value: an int or float to be encrypted.
            If int, it must satisfy abs(*value*) < :attr:`n`/3.
            If float, it must satisfy abs(*value* / *precision*) <<
            :attr:`n`/3
            (i.e. if a float is near the limit then detectable
            overflow may still occur)
          precision (float): Passed to :meth:`EncodedNumber.encode`.
            If *value* is a float then *precision* is the maximum
            **absolute** error allowed when encoding *value*. Defaults
            to encoding *value* exactly.
          r_value (int): obfuscator for the ciphertext; by default (i.e.
            if *r_value* is None), a random value is used.
        Returns:
          EncryptedNumber: An encryption of *value*.
        Raises:
          ValueError: if *value* is out of range or *precision* is so
            high that *value* is rounded to zero.
        """
        if isinstance(value, EncodedNumber):
            encoding = value
        else:
            encoding = EncodedNumber.encode(self.n, self.max_int, value, precision)

        return self.encrypt_encoded(encoding, r_value)

    def encrypt_new(self, value, precision=None):
        """
        新增的接口，取消了之前接口当中密文每个都需要绑定公钥的设定。
        """
        if isinstance(value, EncodedVector):
            encoding = value
        else:
            encoding = EncodedVector.encode(self.n, self.max_int, value, precision)

        return self.encrypt_encoded_new(encoding)


    def encrypt_encoded(self, encoding, r_value):
        """Paillier encrypt an encoded value.
        Args:
          encoding: The EncodedNumber instance.
          r_value (int): obfuscator for the ciphertext; by default (i.e.
            if *r_value* is None), a random value is used.
        Returns:
          EncryptedNumber: An encryption of *value*.
        """
        # If r_value is None, obfuscate in a call to .obfuscate() (below)
        obfuscator = r_value or 1
        #print(f"encoding.encoding: {encoding.encoding}")
        ciphertext = self.raw_encrypt(encoding.encoding, r_value=obfuscator)
        encrypted_number = EncryptedNumber(self.n, self.nsquare, self.max_int, ciphertext, encoding.exponent)
        # Now we do obfuscate in raw_encrypt()
        #if r_value is None:
        #    encrypted_number.obfuscate()
        return encrypted_number

    def encrypt_encoded_new(self, encoding):

        # ciphertext = self.raw_encrypt(encoding.encoding)
        ciphertext = np.array([self.raw_encrypt(plaintext) for plaintext in encoding.encoding])
        # encrypted_public = EncryptedPublic(self.n, self.nsquare, self.max_int, encoding.exponent)
        encrypted_number = EncryptedVector(self.n, self.nsquare, self.max_int, ciphertext, encoding.exponent)
        #if r_value is None:
        #    encrypted_number.obfuscate()
        return encrypted_number


class PaillierPrivateKey(object):
    """Contains a private key and associated decryption method.
    Args:
      public_key (:class:`PaillierPublicKey`): The corresponding public
        key.
      p (int): private secret - see Paillier's paper.
      q (int): private secret - see Paillier's paper.
    Attributes:
      public_key (PaillierPublicKey): The corresponding public
        key.
      p (int): private secret - see Paillier's paper.
      q (int): private secret - see Paillier's paper.
      psquare (int): p^2
      qsquare (int): q^2
      p_inverse (int): p^-1 mod q
      hp (int): h(p) - see Paillier's paper.
      hq (int): h(q) - see Paillier's paper.
    """
    def __init__(self, public_key, p, q):
        if not p*q == public_key.n:
            raise ValueError('given public key does not match the given p and q.')
        if p == q:
            # check that p and q are different, otherwise we can't compute p^-1 mod q
            raise ValueError('p and q have to be different')
        self.public_key = public_key
        if q < p: #ensure that p < q.
            self.p = q
            self.q = p
        else:
            self.p = p
            self.q = q
        self.psquare = self.p * self.p
        self.qsquare = self.q * self.q
        self.p_inverse = invert(self.p, self.q)
        self.hp = self.h_function(self.p, self.psquare)
        self.hq = self.h_function(self.q, self.qsquare)

    @staticmethod
    def from_totient(public_key, totient):
        """given the totient, one can factorize the modulus
        The totient is defined as totient = (p - 1) * (q - 1),
        and the modulus is defined as modulus = p * q
        Args:
          public_key (PaillierPublicKey): The corresponding public
            key
          totient (int): the totient of the modulus
        Returns:
          the :class:`PaillierPrivateKey` that corresponds to the inputs
        Raises:
          ValueError: if the given totient is not the totient of the modulus
            of the given public key
        """
        p_plus_q = public_key.n - totient + 1
        p_minus_q = isqrt(p_plus_q * p_plus_q - public_key.n * 4)
        q = (p_plus_q - p_minus_q) // 2
        p = p_plus_q - q
        if not p*q == public_key.n:
            raise ValueError('given public key and totient do not match.')
        return PaillierPrivateKey(public_key, p, q)

    def __repr__(self):
        pub_repr = repr(self.public_key)
        return "<PaillierPrivateKey for {}>".format(pub_repr)

    def decrypt(self, encrypted_number):
        """Return the decrypted & decoded plaintext of *encrypted_number*.
        Uses the default :class:`EncodedNumber`, if using an alternative encoding
        scheme, use :meth:`decrypt_encoded` or :meth:`raw_decrypt` instead.
        Args:
          encrypted_number (EncryptedNumber): an
            :class:`EncryptedNumber` with a public key that matches this
            private key.
        Returns:
          the int or float that `EncryptedNumber` was holding. N.B. if
            the number returned is an integer, it will not be of type
            float.
        Raises:
          TypeError: If *encrypted_number* is not an
            :class:`EncryptedNumber`.
          ValueError: If *encrypted_number* was encrypted against a
            different key.
        """
        encoded = self.decrypt_encoded(encrypted_number)
        return encoded.decode()


    def decrypt_new(self, cipher_text):

        # encrypted_number = EncryptedNumber(encrypted_public.n, encrypted_public.nsquare, encrypted_public.max_int, cipher_text, encrypted_public.exponent)

        encoded = self.decrypt_encoded_new(cipher_text)
        return encoded.decode()

    def decrypt_no_decode(self, cipher_text):
        # encrypted_number = EncryptedNumber(encrypted_public.n, encrypted_public.nsquare, encrypted_public.max_int, cipher_text, encrypted_public.exponent)
        encoded = self.decrypt_encoded_new(cipher_text)
        # print(f"encoded.encoding = {encoded.encoding}")
        return encoded.encoding

    def decrypt_encoded_new(self, encrypted_number, Encoding=None):
        if not isinstance(encrypted_number, EncryptedVector):
            raise TypeError('Expected encrypted_number to be an EncryptedNumber'
                            ' not: %s' % type(encrypted_number))

        if self.public_key.n != encrypted_number.n:
            raise ValueError('encrypted_number was encrypted against a '
                             'different key!')

        if Encoding is None:
            Encoding = EncodedVector

        # print("encrypted_number shape = ",encrypted_number.ciphertext.shape)
        # print(f"ciphertext = {encrypted_number.ciphertext}")
        encoded = [self.raw_decrypt(ciphertext) for ciphertext in encrypted_number.ciphertext]
        # print(f"encoded = {encoded}")
        # print(f"encoding shape = {np.array(encoded).shape}")
        return Encoding(self.public_key.n, self.public_key.max_int, encoded,
                        encrypted_number.exponent)

    def decrypt_encoded(self, encrypted_number, Encoding=None):
        """Return the :class:`EncodedNumber` decrypted from *encrypted_number*.
        Args:
          encrypted_number (EncryptedNumber): an
            :class:`EncryptedNumber` with a public key that matches this
            private key.
          Encoding (class): A class to use instead of :class:`EncodedNumber`, the
            encoding used for the *encrypted_number* - used to support alternative
            encodings.
        Returns:
          :class:`EncodedNumber`: The decrypted plaintext.
        Raises:
          TypeError: If *encrypted_number* is not an
            :class:`EncryptedNumber`.
          ValueError: If *encrypted_number* was encrypted against a
            different key.
        """
        if not isinstance(encrypted_number, EncryptedNumber):
            raise TypeError('Expected encrypted_number to be an EncryptedNumber'
                            ' not: %s' % type(encrypted_number))

        if self.public_key.n != encrypted_number.n:
            raise ValueError('encrypted_number was encrypted against a '
                             'different key!')

        if Encoding is None:
            Encoding = EncodedNumber

        encoded = self.raw_decrypt(encrypted_number.ciphertext)
        return Encoding(self.public_key.n, self.public_key.max_int, encoded,
                             encrypted_number.exponent)

    def raw_decrypt(self, ciphertext):
        """Decrypt raw ciphertext and return raw plaintext.
        Args:
          ciphertext (int): (usually from :meth:`EncryptedNumber.ciphertext()`)
            that is to be Paillier decrypted.
        Returns:
          int: Paillier decryption of ciphertext. This is a positive
          integer < :attr:`public_key.n`.
        Raises:
          TypeError: if ciphertext is not an int.
        """
        if not isinstance(ciphertext, int):
            raise TypeError('Expected ciphertext to be an int, not: %s' %
                type(ciphertext))

        #decrypt_to_p = self.l_function(powmod(ciphertext, self.p-1, self.psquare), self.p) * self.hp % self.p
        #decrypt_to_q = self.l_function(powmod(ciphertext, self.q-1, self.qsquare), self.q) * self.hq % self.q
        decrypt_to_p = mul_mod(self.l_function(powmod(ciphertext, self.p-1, self.psquare), self.p), self.hp, self.p)
        decrypt_to_q = mul_mod(self.l_function(powmod(ciphertext, self.q-1, self.qsquare), self.q), self.hq, self.q)
        return self.crt(decrypt_to_p, decrypt_to_q)

    def h_function(self, x, xsquare):
        """Computes the h-function as defined in Paillier's paper page 12,
        'Decryption using Chinese-remaindering'.
        """
        return invert(self.l_function(powmod(self.public_key.g, x - 1, xsquare),x), x)

    def l_function(self, x, p):
        """Computes the L function as defined in Paillier's paper. That is: L(x,p) = (x-1)/p"""
        return (x - 1) // p

    def crt(self, mp, mq):
        """The Chinese Remainder Theorem as needed for decryption. Returns the solution modulo n=pq.
        Args:
           mp(int): the solution modulo p.
           mq(int): the solution modulo q.
       """
        #u = (mq - mp) * self.p_inverse % self.q
        u = mul_mod_new((mq - mp), self.p_inverse, self.q)
        # print(f"m_q =  {mq} \n m_p = {mp} \n  (mq - mp) = {(mq - mp)} \n u = {u}")
        return mp + (u * self.p)

    def __eq__(self, other):
        return self.p == other.p and self.q == other.q

    def __hash__(self):
        return hash((self.p, self.q))

class EncryptedNumber(object):
    """Represents the Paillier encryption of a float or int.
    Typically, an `EncryptedNumber` is created by
    :meth:`PaillierPublicKey.encrypt`. You would only instantiate an
    `EncryptedNumber` manually if you are de-serializing a number
    someone else encrypted.
    Paillier encryption is only defined for non-negative integers less
    than :attr:`PaillierPublicKey.n`. :class:`EncodedNumber` provides
    an encoding scheme for floating point and signed integers that is
    compatible with the partially homomorphic properties of the Paillier
    cryptosystem:
    1. D(E(a) * E(b)) = a + b
    2. D(E(a)**b)     = a * b
    where `a` and `b` are ints or floats, `E` represents encoding then
    encryption, and `D` represents decryption then decoding.
    Args:
      public_key (PaillierPublicKey): the :class:`PaillierPublicKey`
        against which the number was encrypted.
      ciphertext (int): encrypted representation of the encoded number.
      exponent (int): used by :class:`EncodedNumber` to keep track of
        fixed precision. Usually negative.
    Attributes:
      public_key (PaillierPublicKey): the :class:`PaillierPublicKey`
        against which the number was encrypted.
      exponent (int): used by :class:`EncodedNumber` to keep track of
        fixed precision. Usually negative.
    Raises:
      TypeError: if *ciphertext* is not an int, or if *public_key* is
        not a :class:`PaillierPublicKey`.
    """
    def __init__(self, n, nsquare, max_int, ciphertext, exponent=0):
        self.n = n
        self.nsquare = nsquare
        self.max_int = max_int
        self.ciphertext = ciphertext
        self.exponent = exponent
        if isinstance(self.ciphertext, EncryptedNumber):
            raise TypeError('ciphertext should be an integer')
        #if not isinstance(self.public_key, PaillierPublicKey):
        #    raise TypeError('public_key should be a PaillierPublicKey')

    def __add__(self, other):
        """Add an int, float, `EncryptedNumber` or `EncodedNumber`."""
        # print("in the add ")
        if isinstance(other, EncryptedNumber):
            return self._add_encrypted(other)
        elif isinstance(other, EncodedNumber):
            return self._add_encoded(other)
        else:
            return self._add_scalar(other)

    @staticmethod
    def vector_add(cipher_text_1, cipher_text_2, public):
        if isinstance(cipher_text_2, EncryptedNumber):
            return cipher_text_1._add_encrypted(cipher_text_2)
        elif isinstance(cipher_text_2, EncodedNumber):
            return cipher_text_1._add_encoded(cipher_text_2)
        else:
            return cipher_text_1._add_scalar(cipher_text_2)

    def __radd__(self, other):
        """Called when Python evaluates `34 + <EncryptedNumber>`
        Required for builtin `sum` to work.
        """
        return self.__add__(other)

    def __mul__(self, other):
        """Multiply by an int, float, or EncodedNumber."""
        if isinstance(other, EncryptedNumber):
            raise NotImplementedError('Good luck with that...')

        if isinstance(other, EncodedNumber):
            encoding = other
        else:
            encoding = EncodedNumber.encode(self.n, self.max_int, other)
        product = self._raw_mul(encoding.encoding)
        exponent = self.exponent + encoding.exponent

        return EncryptedNumber(self.n, self.nsquare, self.max_int, product, exponent)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __sub__(self, other):
        return self + (other * -1)

    def __rsub__(self, other):
        return other + (self * -1)

    def __truediv__(self, scalar):
        return self.__mul__(1 / scalar)

    def decrease_exponent_to(self, new_exp):
        """Return an EncryptedNumber with same value but lower exponent.
        If we multiply the encoded value by :attr:`EncodedNumber.BASE` and
        decrement :attr:`exponent`, then the decoded value does not change.
        Thus we can almost arbitrarily ratchet down the exponent of an
        `EncryptedNumber` - we only run into trouble when the encoded
        integer overflows. There may not be a warning if this happens.
        When adding `EncryptedNumber` instances, their exponents must
        match.
        This method is also useful for hiding information about the
        precision of numbers - e.g. a protocol can fix the exponent of
        all transmitted `EncryptedNumber` instances to some lower bound(s).
        Args:
          new_exp (int): the desired exponent.
        Returns:
          EncryptedNumber: Instance with the same plaintext and desired
            exponent.
        Raises:
          ValueError: You tried to increase the exponent.
        """
        if new_exp > self.exponent:
            raise ValueError('New exponent %i should be more negative than '
                             'old exponent %i' % (new_exp, self.exponent))
        multiplied = self * pow(EncodedNumber.BASE, self.exponent - new_exp)
        multiplied.exponent = new_exp
        return multiplied

    def _add_scalar(self, scalar):
        """Returns E(a + b), given self=E(a) and b.
        Args:
          scalar: an int or float b, to be added to `self`.
        Returns:
          EncryptedNumber: E(a + b), calculated by encrypting b and
            taking the product of E(a) and E(b) modulo
            :attr:`~PaillierPublicKey.n` ** 2.
        Raises:
          ValueError: if scalar is out of range or precision.
        """
        encoded = EncodedNumber.encode(self.n, self.max_int, scalar,
                                       max_exponent=self.exponent)

        return self._add_encoded(encoded)

    def _add_encoded(self, encoded):
        """Returns E(a + b), given self=E(a) and b.
        Args:
          encoded (EncodedNumber): an :class:`EncodedNumber` to be added
            to `self`.
        Returns:
          EncryptedNumber: E(a + b), calculated by encrypting b and
            taking the product of E(a) and E(b) modulo
            :attr:`~PaillierPublicKey.n` ** 2.
        Raises:
          ValueError: if scalar is out of range or precision.
        """
        if self.n != encoded.n:
            raise ValueError("Attempted to add numbers encoded against "
                             "different public keys!")

        # In order to add two numbers, their exponents must match.
        a, b = self, encoded
        if a.exponent > b.exponent:
            a = self.decrease_exponent_to(b.exponent)
        elif a.exponent < b.exponent:
            b = b.decrease_exponent_to(a.exponent)

        # Don't bother to salt/obfuscate in a basic operation, do it
        # just before leaving the computer.
        encrypted_scalar = a._raw_encrypt(b.encoding)

        sum_ciphertext = a._raw_add(a.ciphertext, encrypted_scalar)
        return EncryptedNumber(a.n, a.nsquare, a.max_int, sum_ciphertext, a.exponent)

    def _raw_encrypt(self, plaintext):
        """Paillier encryption of a positive integer plaintext < :attr:`n`.
        You probably should be using :meth:`encrypt` instead, because it
        handles positive and negative ints and floats.
        Args:
          plaintext (int): a positive integer < :attr:`n` to be Paillier
            encrypted. Typically this is an encoding of the actual
            number you want to encrypt.
          r_value (int): obfuscator for the ciphertext; by default (i.e.
            r_value is None), a random value is used.
        Returns:
          int: Paillier encryption of plaintext.
        Raises:
          TypeError: if plaintext is not an int.
        """
        if not isinstance(plaintext, int):
            raise TypeError('Expected int type plaintext but got: %s' %
                            type(plaintext))

        if self.n - self.max_int <= plaintext < self.n:
            # Very large plaintext, take a sneaky shortcut using inverses
            neg_plaintext = self.n - plaintext  # = abs(plaintext - nsquare)
            neg_ciphertext = mod(mul(self.n, neg_plaintext) + 1, self.nsquare)
            nude_ciphertext = invert(neg_ciphertext, self.nsquare)
        else:
            # we chose g = n + 1, so that we can exploit the fact that
            # (n+1)^plaintext = n*plaintext + 1 mod n^2
            nude_ciphertext = mod(mul(self.n, plaintext) +1, self.nsquare)
        return nude_ciphertext

    def _add_encrypted(self, other):
        """Returns E(a + b) given E(a) and E(b).
        Args:
          other (EncryptedNumber): an `EncryptedNumber` to add to self.
        Returns:
          EncryptedNumber: E(a + b), calculated by taking the product
            of E(a) and E(b) modulo :attr:`~PaillierPublicKey.n` ** 2.
        Raises:
          ValueError: if numbers were encrypted against different keys.
        """
        if self.n != other.n:
            raise ValueError("Attempted to add numbers encrypted against "
                             "different public keys!")

        # In order to add two numbers, their exponents must match.
        a, b = self, other
        if a.exponent > b.exponent:
            a = self.decrease_exponent_to(b.exponent)
        elif a.exponent < b.exponent:
            b = b.decrease_exponent_to(a.exponent)

        # t_0 = time.time()
        sum_ciphertext = a._raw_add(a.ciphertext, b.ciphertext)
        # t_1 = time.time()
        output = EncryptedNumber(a.n, a.nsquare, a.max_int, sum_ciphertext, a.exponent)
        # t_2 = time.time()
        # print(f"time of v1 = {t_2 - t_0} part_1 = {t_1 - t_0} part_2 = {t_2 - t_1}")
        return output

    def _raw_add(self, e_a, e_b):
        """Returns the integer E(a + b) given ints E(a) and E(b).
        N.B. this returns an int, not an `EncryptedNumber`, and ignores
        :attr:`ciphertext`
        Args:
          e_a (int): E(a), first term
          e_b (int): E(b), second term
        Returns:
          int: E(a + b), calculated by taking the product of E(a) and
            E(b) modulo :attr:`~PaillierPublicKey.n` ** 2.
        """
        return mul_mod(e_a,e_b,self.nsquare)
        #return e_a * e_b % self.nsquare

    def _raw_mul(self, plaintext):
        """Returns the integer E(a * plaintext), where E(a) = ciphertext
        Args:
          plaintext (int): number by which to multiply the
            `EncryptedNumber`. *plaintext* is typically an encoding.
            0 <= *plaintext* < :attr:`~PaillierPublicKey.n`
        Returns:
          int: Encryption of the product of `self` and the scalar
            encoded in *plaintext*.
        Raises:
          TypeError: if *plaintext* is not an int.
          ValueError: if *plaintext* is not between 0 and
            :attr:`PaillierPublicKey.n`.
        """
        if not isinstance(plaintext, int):
            raise TypeError('Expected ciphertext to be int, not %s' %
                type(plaintext))

        if plaintext < 0 or plaintext >= self.n:
            raise ValueError('Scalar out of bounds: %i' % plaintext)

        if self.n - self.max_int <= plaintext:
            # Very large plaintext, play a sneaky trick using inverses
            neg_c = invert(self.ciphertext, self.nsquare)
            neg_scalar = self.n - plaintext
            return powmod(neg_c, neg_scalar, self.nsquare)
        else:
            return powmod(self.ciphertext, plaintext, self.nsquare)


class EncryptedVector(object):

    def __init__(self, n, nsquare, max_int, ciphertext, exponent=0):
        self.n = n
        # g = n+1
        self.nsquare = nsquare
        self.max_int = max_int
        self.ciphertext = ciphertext # vector
        self.exponent = exponent
        if isinstance(self.ciphertext, EncryptedNumber):
            raise TypeError('ciphertext should be an integer')
        #if not isinstance(self.public_key, PaillierPublicKey):
        #    raise TypeError('public_key should be a PaillierPublicKey')

    def __add__(self, other):
        """Add an int, float, `EncryptedNumber` or `EncodedNumber`."""

        if isinstance(other, EncryptedVector):
            return self._add_encrypted(other)
        elif isinstance(other, EncodedVector):
            return self._add_encoded(other)
        else:
            return self._add_scalar(other)

    def __radd__(self, other):
        return self.__add__(other)

    def __getitem__(self, item):
        if isinstance(item, int):
            return EncryptedVector(self.n, self.nsquare, self.max_int, np.array([self.ciphertext[item]]), self.exponent)
        else:
            return EncryptedVector(self.n, self.nsquare, self.max_int, self.ciphertext[item], self.exponent)

    def __setitem__(self, key, value):
        self.ciphertext[key] = value

    def __mul__(self, other):
        if isinstance(other, EncryptedVector):
            raise NotImplementedError('paillier作为加法同态不支持乘法同态计算，Good luck with that...')
        if np.isscalar(other):
            other = [other]
            encoding = EncodedVector.encode(self.n, self.max_int, other)
            product = np.array([self._raw_mul_2(cipher, encoding.encoding[0]) for cipher in self.ciphertext])
            exponent = self.exponent + encoding.exponent
        else:
            if (len(other) == len(self.ciphertext)):
                product = []
                other = other.tolist()
                encodings = EncodedVector.encode(self.n, self.max_int, other)
                for i in range(len(self.ciphertext)):
                    mul_res_tmp = self._raw_mul_2(self.ciphertext[i], encodings.encoding[i])
                    product.append(mul_res_tmp)
                product = np.array(product)
                exponent = self.exponent + encodings.exponent
            else:
                raise TypeError("Not at same shape")
        return EncryptedVector(self.n, self.nsquare, self.max_int, product, exponent)

    def unpack_vector(self, ind, num_in_one_pack, shift_positon=32):
        vector_ind = int(ind / num_in_one_pack)
        cipher_ind = int(ind % num_in_one_pack)
        tmp_cipher = self.ciphertext[vector_ind]
        # print(f"tmp_cipher = {tmp_cipher}")
        shift_per = 2 ** shift_positon
        shift_lens = 1

        shift_lens = powmod(shift_per, cipher_ind, self.nsquare)
        # for _ in range(cipher_ind):
        #     shift_lens = mul_mod(shift_lens, shift_per, self.nsquare)
        # print(f"shift_lens = {shift_lens}")
        # print(f"vector_ind = {vector_ind} cipher_ind = {cipher_ind} np.log2(self.nsquare) = {self.nsquare.bit_length()}")
        encoding = EncodedVector.encode(self.n, self.max_int, [shift_lens])
        tmp_cipher = np.array([self._raw_mul_2(tmp_cipher, encoding.encoding[0])])
        # print(f"tmp_cipher = {tmp_cipher}")
        return EncryptedVector(self.n, self.nsquare, self.max_int, tmp_cipher, self.exponent)

    def pack_blender(self,num_in_one_pack, xgb_pack_switch=False):
        # random_num = [0 for _ in range(num_in_one_pack * 2)]
        random_num = np.random.randint(2**30, 2**31, num_in_one_pack*2).tolist()
        random_num[num_in_one_pack] = 0
        if xgb_pack_switch:
            random_num[num_in_one_pack + 1]=0
        value = random_num[0] & 0xFFFFFFFF
        for i in range(num_in_one_pack*2-1):
            value = value << 32
            value |= (random_num[i+1] & 0xFFFFFFFF)
        encoding = EncodedVector.encode(self.n, self.max_int, [value])

        encrypted_scalar = self._raw_encrypt(encoding.encoding)

        sum_ciphertext = [self._raw_add(self.ciphertext[0], encrypted_scalar[0])]

        return EncryptedVector(self.n, self.nsquare, self.max_int, sum_ciphertext, self.exponent)


    @staticmethod
    def bind_to_vector(cipher_list):
        tmp_cipher = cipher_list[0]
        if len(tmp_cipher.ciphertext) != 0:
            assert (f"Only support to bind ONE cipher list in to EncryptedVector, but get {len(cipher_list[0].ciphertext)}")
        product = []
        for i in range(len(cipher_list)):
            product.append(cipher_list[i].ciphertext[0])
        product = np.array(product)
        return EncryptedVector(tmp_cipher.n, tmp_cipher.nsquare, tmp_cipher.max_int, product, tmp_cipher.exponent)

    def __rmul__(self, other):
        return self.__mul__(other)

    def __sub__(self, other):
        return self + (other * -1)

    def __rsub__(self, other):
        return other + (self * -1)

    def __truediv__(self, scalar):
        return self.__mul__(1 / scalar)

    def shift_cipher(self):
        return self * (2 ** 32)

    def decrease_exponent_to(self, new_exp):
        if new_exp > self.exponent:
            raise ValueError('New exponent %i should be more negative than '
                             'old exponent %i' % (new_exp, self.exponent))
        multiplied = self * pow(EncodedNumber.BASE, self.exponent - new_exp)
        multiplied.exponent = new_exp
        return multiplied

    def _add_scalar(self, scalar):
        if not(isinstance(scalar, np.ndarray)):
            scalar = np.array([scalar])
        # print(f"in add scalar {scalar}")
        encoded = EncodedVector.encode(self.n, self.max_int, scalar,
                                           max_exponent=self.exponent)

        return self._add_encoded_scalar(encoded)

    def _add_encoded_scalar(self, encoded):
        if self.n != encoded.n:
            raise ValueError("Attempted to add numbers encoded against "
                             "different public keys!")

        # In order to add two numbers, their exponents must match.
        a, b = self, encoded
        if a.exponent > b.exponent:
            a = self.decrease_exponent_to(b.exponent)
        elif a.exponent < b.exponent:
            b = b.decrease_exponent_to(a.exponent)

        # Don't bother to salt/obfuscate in a basic operation, do it
        # just before leaving the computer.
        encrypted_scalar = a._raw_encrypt(b.encoding)
        # encrypted_scalar = encrypted_scalar.astype(int)

        sum_ciphertext = [a._raw_add(a.ciphertext[i], encrypted_scalar[i]) for i in range(len(encrypted_scalar))]
        return EncryptedVector(a.n, a.nsquare, a.max_int, sum_ciphertext, a.exponent)

    def _add_encoded(self, encoded):
        if self.n != encoded.n:
            raise ValueError("Attempted to add numbers encoded against "
                             "different public keys!")

        # In order to add two numbers, their exponents must match.
        a, b = self, encoded
        if a.exponent > b.exponent:
            a = self.decrease_exponent_to(b.exponent)
        elif a.exponent < b.exponent:
            b = b.decrease_exponent_to(a.exponent)

        # Don't bother to salt/obfuscate in a basic operation, do it
        # just before leaving the computer.
        encrypted_scalar = a._raw_encrypt(b.encoding)
        encrypted_scalar = encrypted_scalar.astype(int)

        sum_ciphertext = [a._raw_add(a.ciphertext[i], encrypted_scalar[i]) for i in range(len(encrypted_scalar))]
        return EncryptedVector(a.n, a.nsquare, a.max_int, sum_ciphertext, a.exponent)

    def _raw_encrypt(self, plaintextvector):

        nude_ciphertext = []
        for plaintext in plaintextvector:
            if not isinstance(plaintext, int):
                raise TypeError('Expected int type plaintext but got: %s' %
                                type(plaintext))

            if self.n - self.max_int <= plaintext < self.n:
                # Very large plaintext, take a sneaky shortcut using inverses
                neg_plaintext = self.n - plaintext  # = abs(plaintext - nsquare)
                neg_ciphertext = mod(mul(self.n, neg_plaintext) + 1, self.nsquare)
                nude_ciphertext.append(invert(neg_ciphertext, self.nsquare))
            else:
                # we chose g = n + 1, so that we can exploit the fact that
                # (n+1)^plaintext = n*plaintext + 1 mod n^2
                nude_ciphertext.append(mod(mul(self.n, plaintext) +1, self.nsquare))
        nude_ciphertext = np.array(nude_ciphertext)
        return nude_ciphertext

    def _add_encrypted(self, other):
        if self.n != other.n:
            raise ValueError("Attempted to add numbers encrypted against "
                             "different public keys!")

        # In order to add two numbers, their exponents must match.
        a, b = self, other
        if a.exponent > b.exponent:
            a = self.decrease_exponent_to(b.exponent)
        elif a.exponent < b.exponent:
            b = b.decrease_exponent_to(a.exponent)

        sum_ciphertext = [a._raw_add(a.ciphertext[i], b.ciphertext[i]) for i in range(len(a.ciphertext))]
        return EncryptedVector(a.n, a.nsquare, a.max_int, sum_ciphertext, a.exponent)

    def _raw_add(self, e_a, e_b):
        e_b = int(e_b)
        return mul_mod(e_a,e_b,self.nsquare)
        #return e_a * e_b % self.nsquare

    def _raw_mul(self, plaintext):
        if not isinstance(plaintext, int):
            raise TypeError('Expected ciphertext to be int, not %s' %
                            type(plaintext))

        if plaintext < 0 or plaintext >= self.n:
            raise ValueError('Scalar out of bounds: %i' % plaintext)

        if self.n - self.max_int <= plaintext:
            # Very large plaintext, play a sneaky trick using inverses
            neg_c = invert(self.ciphertext, self.nsquare)
            neg_scalar = self.n - plaintext
            return powmod(neg_c, neg_scalar, self.nsquare)
        else:
            return powmod(self.ciphertext, plaintext, self.nsquare)

    def _raw_mul_2(self, ciphertext, plaintext):
        if not isinstance(plaintext, int):
            raise TypeError('Expected ciphertext to be int, not %s' %
                            type(plaintext))

        if plaintext < 0 or plaintext >= self.n:
            raise ValueError('Scalar out of bounds: %i' % plaintext)

        if self.n - self.max_int <= plaintext:
            # Very large plaintext, play a sneaky trick using inverses
            neg_c = invert(ciphertext, self.nsquare)
            neg_scalar = self.n - plaintext
            return powmod(neg_c, neg_scalar, self.nsquare)
        else:
            return powmod(ciphertext, plaintext, self.nsquare)

    def sum(self, shape, dim=1):
        if len(shape) == 1:
            shape = [1, shape[0]]
        row = shape[0]
        colum = shape[1]
        sum_out_vector = []
        if dim == 0:
            for i in range(colum):
                sum_out = 1
                for j in range(row):
                    sum_out = self._raw_add(sum_out, self.ciphertext[i + colum * j])
                sum_out_vector.append(sum_out)
            sum_out_vector = np.array(sum_out_vector)
        elif dim == 1:
            for i in range(row):
                sum_out = 1
                for j in range(colum):
                    sum_out = self._raw_add(sum_out, self.ciphertext[colum * i + j])
                sum_out_vector.append(sum_out)
            sum_out_vector = np.array(sum_out_vector)
        else:
            raise ValueError('dim can only be 0 or 1')
        return EncryptedVector(self.n, self.nsquare, self.max_int, sum_out_vector, self.exponent)