
import phe.paillier as paillier
if __name__ == '__main__':
    # 假设有一个 Paillier 公钥 `public_key` 和需要加密的向量 `vector`
    vector = [3.5, 2.1, 7.9]  # 需要加密的浮点数向量

    public_key, private_key = paillier.generate_paillier_keypair()
    ciphertext = public_key.encrypt_new(vector)
    ciphertext = ciphertext+ ciphertext  # 加密两次向量，得到的结果是 2 * vector
    plaintext = private_key.decrypt_new(ciphertext)
    ciphertext = ciphertext* 4  # 加密两次向量，得到的结果是 2 * vector
    plaintext2 = private_key.decrypt_new(ciphertext)

    print(plaintext.tolist())  # 输出：[7.   4.2 15.8]
    print(plaintext2)  # 输出：[14.   8.4 31.6]