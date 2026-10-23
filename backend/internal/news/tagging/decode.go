package tagging

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"slices"
	"unicode/utf8"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
)

// Decode accepts only the fixed wire contract; it never repairs or echoes model output.
func Decode(v vocabulary.Vocabulary, text, response string) (store.TaggingResult, error) {
	if !utf8.ValidString(response) {
		return store.TaggingResult{}, errors.New("tagging response is not valid UTF-8")
	}
	fields, err := object([]byte(response), "tags", "events")
	if err != nil {
		return store.TaggingResult{}, err
	}
	if err := objects(fields["tags"], "tag_id", "evidence"); err != nil {
		return store.TaggingResult{}, err
	}
	if err := objects(fields["events"], "tag_id", "status", "evidence"); err != nil {
		return store.TaggingResult{}, err
	}
	var result store.TaggingResult
	if err := json.Unmarshal([]byte(response), &result); err != nil {
		return store.TaggingResult{}, errors.New("tagging response fields have invalid types")
	}
	if err := store.ValidateTaggingResult(v, text, result); err != nil {
		return store.TaggingResult{}, err
	}
	return result, nil
}

func object(data []byte, required ...string) (map[string]json.RawMessage, error) {
	d := json.NewDecoder(bytes.NewReader(data))
	start, err := d.Token()
	if err != nil || start != json.Delim('{') {
		return nil, errors.New("tagging response requires a JSON object")
	}
	fields := make(map[string]json.RawMessage, len(required))
	for d.More() {
		token, err := d.Token()
		if err != nil {
			return nil, errors.New("tagging response contains malformed JSON")
		}
		key, ok := token.(string)
		if !ok || !slices.Contains(required, key) || fields[key] != nil {
			return nil, errors.New("tagging response contains an unknown or duplicate field")
		}
		var value json.RawMessage
		if err := d.Decode(&value); err != nil {
			return nil, errors.New("tagging response contains malformed JSON")
		}
		fields[key] = value
	}
	if end, err := d.Token(); err != nil || end != json.Delim('}') {
		return nil, errors.New("tagging response contains malformed JSON")
	}
	if len(fields) != len(required) {
		return nil, errors.New("tagging response is missing a required field")
	}
	if err := d.Decode(new(json.RawMessage)); err != io.EOF {
		return nil, errors.New("tagging response must contain exactly one JSON value")
	}
	return fields, nil
}

func objects(data []byte, required ...string) error {
	data = bytes.TrimSpace(data)
	if len(data) == 0 || data[0] != '[' {
		return errors.New("tagging response lists must be JSON arrays")
	}
	var items []json.RawMessage
	if err := json.Unmarshal(data, &items); err != nil {
		return errors.New("tagging response contains a malformed array")
	}
	for _, item := range items {
		if _, err := object(item, required...); err != nil {
			return err
		}
	}
	return nil
}
