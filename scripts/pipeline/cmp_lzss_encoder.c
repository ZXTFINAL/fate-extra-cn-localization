#include <stdint.h>
#include <stdlib.h>

/*
 * Encode the game's IECP LZSS format. The newest matching three-byte key is
 * sufficient for a valid back-reference and keeps memory bounded to a 16 MiB
 * lookup table, even for the game's large texture packages.
 */
int fate_cmp_encode(const uint8_t *input, uint32_t input_len,
                    uint8_t **output, uint32_t *output_len) {
    if (!input || !output || !output_len) return 1;
    if (input_len > UINT32_MAX - input_len / 8 - 16) return 2;

    const uint32_t key_count = 1u << 24;
    uint32_t *last = (uint32_t *)malloc((size_t)key_count * sizeof(uint32_t));
    if (!last) return 3;
    for (uint32_t i = 0; i < key_count; ++i) last[i] = UINT32_MAX;

    size_t capacity = (size_t)input_len + (input_len + 7u) / 8u + 8u;
    uint8_t *out = (uint8_t *)malloc(capacity ? capacity : 8u);
    if (!out) {
        free(last);
        return 4;
    }
    out[0] = 'I'; out[1] = 'E'; out[2] = 'C'; out[3] = 'P';
    out[4] = (uint8_t)(input_len & 0xff);
    out[5] = (uint8_t)((input_len >> 8) & 0xff);
    out[6] = (uint8_t)((input_len >> 16) & 0xff);
    out[7] = (uint8_t)((input_len >> 24) & 0xff);

    size_t out_pos = 8;
    uint32_t pos = 0;
    while (pos < input_len) {
        size_t control_pos = out_pos++;
        uint8_t control = 0;
        for (unsigned bit = 0; bit < 8 && pos < input_len; ++bit) {
            uint32_t best_len = 0;
            uint32_t candidate = UINT32_MAX;
            uint32_t limit = input_len - pos;
            if (limit > 18) limit = 18;

            if (limit >= 3) {
                uint32_t key = ((uint32_t)input[pos] << 16) |
                               ((uint32_t)input[pos + 1] << 8) |
                               (uint32_t)input[pos + 2];
                candidate = last[key];
                if (candidate != UINT32_MAX && pos - candidate <= 4096) {
                    uint32_t distance = pos - candidate;
                    uint32_t length = 3;
                    while (length < limit &&
                           input[candidate + (length % distance)] == input[pos + length]) {
                        ++length;
                    }
                    if (length >= 3) best_len = length;
                }
            }

            uint32_t length;
            if (best_len >= 3) {
                uint32_t source = (0xfee + candidate) & 0xfff;
                out[out_pos++] = (uint8_t)(source & 0xff);
                out[out_pos++] = (uint8_t)(((source >> 4) & 0xf0) | (best_len - 3));
                length = best_len;
            } else {
                control |= (uint8_t)(1u << bit);
                out[out_pos++] = input[pos];
                length = 1;
            }

            uint32_t end = pos + length;
            for (uint32_t index = pos; index < end && index + 2 < input_len; ++index) {
                uint32_t key = ((uint32_t)input[index] << 16) |
                               ((uint32_t)input[index + 1] << 8) |
                               (uint32_t)input[index + 2];
                last[key] = index;
            }
            pos = end;
        }
        out[control_pos] = control;
    }

    free(last);
    *output = out;
    *output_len = (uint32_t)out_pos;
    return 0;
}

void fate_cmp_free(void *ptr) { free(ptr); }
