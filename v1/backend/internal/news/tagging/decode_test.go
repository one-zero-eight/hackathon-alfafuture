package tagging

import (
	"reflect"
	"strings"
	"testing"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
)

const articleText = "Oil rose. Oil may fall. A price rise is planned. Oil is uncertain. France. Analyst A expects oil to rise. Analyst B expects oil to fall."

func TestDecodePreservesEmptyDirectAndSeparateEventResults(t *testing.T) {
	v := fixedVocabulary(t)
	for _, tc := range []struct {
		name, response string
		tags, events   int
	}{
		{"empty", " \n {\"tags\":[],\"events\":[]} \t", 0, 0},
		{"direct geography", `{"tags":[{"tag_id":"geography:country:FR","evidence":"France"}],"events":[]}`, 1, 0},
		{"all states", `{"tags":[{"tag_id":"resource:oil","evidence":"Oil"},{"tag_id":"event:commodity_prices","evidence":"Oil rose."}],"events":[{"tag_id":"event:commodity_prices","status":"observed","evidence":"Oil rose."},{"tag_id":"event:commodity_prices","status":"forecast","evidence":"Oil may fall."},{"tag_id":"event:commodity_prices","status":"announced_planned","evidence":"A price rise is planned."},{"tag_id":"event:commodity_prices","status":null,"evidence":"Oil is uncertain."}]}`, 2, 4},
		{"separate forecasts", `{"tags":[{"tag_id":"event:commodity_prices","evidence":"Analyst A expects oil to rise."}],"events":[{"tag_id":"event:commodity_prices","status":"forecast","evidence":"Analyst A expects oil to rise."},{"tag_id":"event:commodity_prices","status":"forecast","evidence":"Analyst B expects oil to fall."}]}`, 1, 2},
	} {
		t.Run(tc.name, func(t *testing.T) {
			result, err := Decode(v, articleText, tc.response)
			if err != nil || len(result.Tags) != tc.tags || len(result.Events) != tc.events || result.Tags == nil || result.Events == nil {
				t.Fatalf("valid result changed: %+v %v", result, err)
			}
			if tc.name == "all states" && (result.Events[3].Status != nil || *result.Events[0].Status != "observed" || *result.Events[1].Status != "forecast" || *result.Events[2].Status != "announced_planned") {
				t.Fatal("per-instance statuses were collapsed or null was fabricated")
			}
		})
	}
}

func TestDecodeRejectsInvalidWireShapeWithoutRepairOrPartialResult(t *testing.T) {
	v := fixedVocabulary(t)
	for _, response := range []string{
		``, `null`, `[]`, `{}`, `{"tags":[]}`, `{"events":[]}`,
		`{"tags":null,"events":[]}`, `{"tags":[],"events":null}`, `{"tags":{},"events":[]}`,
		`{"tags":[],"events":[],"PRIVATE_MODEL_OUTPUT":1}`,
		`{"Tags":[],"events":[]}`, `{"tags":[],"events":[],"tags":[]}`,
		`{"tags":[],"events":[],"t\u0061gs":[]}`,
		`{"tags":[],"events":[]} {"tags":[],"events":[]}`,
		`{"tags":[],"events":[]} trailing`, `{"tags":[],"events":[]} null`,
		"```json\n{\"tags\":[],\"events\":[]}\n```", `{"tags":[],"events":[],}`,
		`{"tags":[null],"events":[]}`, `{"tags":[[]],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil"}],"events":[]}`,
		`{"tags":[{"tag_id":null,"evidence":"Oil"}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":null}],"events":[]}`,
		`{"tags":[{"tag_id":42,"evidence":"Oil"}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":true}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":"Oil","Evidence":"Oil"}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","tag_id":"resource:oil","evidence":"Oil"}],"events":[]}`,
		`{"tags":[],"events":[{"tag_id":"event:commodity_prices","evidence":"Oil"}]}`,
		`{"tags":[],"events":[{"tag_id":"event:commodity_prices","status":1,"evidence":"Oil"}]}`,
		`{"tags":[],"events":[{"tag_id":"event:commodity_prices","status":null,"status":"observed","evidence":"Oil"}]}`,
		`{"tags":[],"events":[{"tag_id":"event:commodity_prices","status":null,"evidence":"Oil","extra":0}]}`,
		`{"tags":[],"events":[null]}`,
		string([]byte{'{', '"', 0xff, '"', ':', '0', '}'}),
	} {
		result, err := Decode(v, articleText, response)
		if err == nil || !reflect.DeepEqual(result, store.TaggingResult{}) || strings.Contains(err.Error(), "PRIVATE_MODEL_OUTPUT") {
			t.Errorf("invalid response accepted, repaired, partially returned or echoed: %q => %+v %v", response, result, err)
		}
	}
}

func TestDecodeUsesFixedIDsLiteralEvidenceAndEventAgreement(t *testing.T) {
	v := fixedVocabulary(t)
	for _, response := range []string{
		`{"tags":[{"tag_id":"invented","evidence":"Oil"}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":"OIL"}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":"Oil  rose."}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":" "}],"events":[]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":"Oil"},{"tag_id":"resource:oil","evidence":"Oil rose."}],"events":[]}`,
		`{"tags":[{"tag_id":"event:commodity_prices","evidence":"Oil"}],"events":[]}`,
		`{"tags":[],"events":[{"tag_id":"event:commodity_prices","status":null,"evidence":"Oil"}]}`,
		`{"tags":[{"tag_id":"resource:oil","evidence":"Oil"}],"events":[{"tag_id":"resource:oil","status":null,"evidence":"Oil"}]}`,
		`{"tags":[{"tag_id":"event:commodity_prices","evidence":"Oil"}],"events":[{"tag_id":"event:commodity_prices","status":"unknown","evidence":"Oil"}]}`,
		`{"tags":[{"tag_id":"event:commodity_prices","evidence":"Oil"}],"events":[{"tag_id":"event:commodity_prices","status":"","evidence":"Oil"}]}`,
		`{"tags":[{"tag_id":"event:commodity_prices","evidence":"Oil"}],"events":[{"tag_id":"event:commodity_prices","status":null,"evidence":"not in article"}]}`,
		`{"tags":[{"tag_id":"event:commodity_prices","evidence":"Oil"}],"events":[{"tag_id":"event:commodity_prices","status":null,"evidence":"Oil"},{"tag_id":"event:commodity_prices","status":null,"evidence":"Oil"}]}`,
	} {
		if result, err := Decode(v, articleText, response); err == nil || !reflect.DeepEqual(result, store.TaggingResult{}) {
			t.Errorf("invalid classification accepted: %s => %+v %v", response, result, err)
		}
	}
}
