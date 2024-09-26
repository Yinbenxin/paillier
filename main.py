import phe.paillier as paillier

if __name__ == '__main__':
    # Generate a public/private key pair
    public_key, private_key = paillier.generate_paillier_keypair(table_path="key_table")

    # Encrypt a plaintext using the public key
    encrypted_number = public_key.encrypt([3.14159,2,3,4,545])

    # Decrypt the encrypted number using the private key
    decrypted_number = private_key.decrypt(encrypted_number)

    print("Encrypted number:", encrypted_number)
    print("Decrypted number:", decrypted_number)