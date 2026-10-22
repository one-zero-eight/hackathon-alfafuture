package store

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

var (
	ErrArticleNotPending    = errors.New("article is not pending")
	ErrAttemptNotProcessing = errors.New("attempt is not processing")
)

type TaggingAttempt struct {
	ID               int64              `gorm:"primaryKey;uniqueIndex:idx_attempt_version"`
	ArticleID        int64              `gorm:"not null;uniqueIndex:idx_article_attempt"`
	Number           int                `gorm:"not null;uniqueIndex:idx_article_attempt;check:attempt_number,number > 0"`
	Version          string             `gorm:"not null;uniqueIndex:idx_attempt_version"`
	PromptVersion    string             `gorm:"not null"`
	Model            string             `gorm:"not null"`
	InputText        string             `gorm:"not null"`
	Request          string             `gorm:"not null"`
	Response         string             `gorm:"not null"`
	StartedAt        time.Time          `gorm:"not null"`
	FinishedAt       *time.Time         `gorm:"check:attempt_finish,(status = 'processing' AND finished_at IS NULL) OR (status <> 'processing' AND finished_at >= started_at AND finished_at IS NOT NULL)"`
	Status           string             `gorm:"not null;check:attempt_status,status IN ('processing','completed','failed')"`
	Error            string             `gorm:"not null"`
	PromptTokens     *int64             `gorm:"check:attempt_prompt_tokens,prompt_tokens >= 0"`
	CompletionTokens *int64             `gorm:"check:attempt_completion_tokens,completion_tokens >= 0"`
	TotalTokens      *int64             `gorm:"check:attempt_total_tokens,total_tokens >= 0"`
	Article          *Article           `gorm:"constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
	Vocabulary       *vocabularyVersion `gorm:"belongsTo:Vocabulary;foreignKey:Version;references:Version;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
	Assignments      []TagAssignment    `gorm:"foreignKey:AttemptID,Version;references:ID,Version;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
	Events           []EventInstance    `gorm:"foreignKey:AttemptID;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

type TagAssignment struct {
	AttemptID int64  `gorm:"primaryKey"`
	TagID     string `gorm:"primaryKey"`
	Version   string `gorm:"not null"`
	Evidence  string `gorm:"not null;check:assignment_evidence,btrim(evidence) <> ''"`
	Tag       *tag   `gorm:"belongsTo:Tag;foreignKey:Version,TagID;references:Version,ID;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

type EventInstance struct {
	ID         int64          `gorm:"primaryKey"`
	AttemptID  int64          `gorm:"not null"`
	TagID      string         `gorm:"not null"`
	Status     *string        `gorm:"check:event_status,status IN ('observed','announced_planned','forecast')"`
	Evidence   string         `gorm:"not null;check:event_evidence,btrim(evidence) <> ''"`
	Assignment *TagAssignment `gorm:"belongsTo:Assignment;foreignKey:AttemptID,TagID;references:AttemptID,TagID;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

type TaggingResult struct {
	Tags   []ResultTag   `json:"tags"`
	Events []ResultEvent `json:"events"`
}

type ResultTag struct {
	TagID    string `json:"tag_id"`
	Evidence string `json:"evidence"`
}

type ResultEvent struct {
	TagID    string  `json:"tag_id"`
	Status   *string `json:"status"`
	Evidence string  `json:"evidence"`
}

type AttemptCompletion struct {
	FinishedAt       time.Time
	Response         string
	PromptTokens     *int64
	CompletionTokens *int64
	TotalTokens      *int64
	Result           *TaggingResult
	Error            string
	// FailureStatus is pending for a scheduled retry or failed for a terminal failure.
	FailureStatus string
}

// StartAttempt saves the exact request before a paid call and claims one pending article.
func StartAttempt(ctx context.Context, db *gorm.DB, input TaggingAttempt) (TaggingAttempt, error) {
	request := strings.TrimSpace(input.Request)
	if input.ID != 0 || input.ArticleID <= 0 || input.StartedAt.IsZero() || strings.TrimSpace(input.Version) == "" || strings.TrimSpace(input.PromptVersion) == "" || strings.TrimSpace(input.Model) == "" || strings.TrimSpace(input.InputText) == "" || !json.Valid([]byte(request)) || !strings.HasPrefix(request, "{") {
		return TaggingAttempt{}, errors.New("attempt requires an unset ID, article, versions, model, text, JSON request object and start time")
	}
	row := TaggingAttempt{ArticleID: input.ArticleID, Version: input.Version, PromptVersion: input.PromptVersion, Model: input.Model, InputText: input.InputText, Request: input.Request, StartedAt: input.StartedAt.UTC(), Status: StatusProcessing}
	err := db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var article Article
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&article, row.ArticleID).Error; err != nil {
			return err
		}
		if article.ProcessingStatus != StatusPending {
			return ErrArticleNotPending
		}
		if row.InputText != article.Text {
			return errors.New("attempt input text must match the stored article snapshot")
		}
		if err := tx.Model(&TaggingAttempt{}).Where("article_id = ?", row.ArticleID).Select("COALESCE(MAX(number), 0) + 1").Scan(&row.Number).Error; err != nil {
			return err
		}
		if err := tx.Omit(clause.Associations).Create(&row).Error; err != nil {
			return err
		}
		return tx.Model(&article).Update("processing_status", StatusProcessing).Error
	})
	if err != nil {
		return TaggingAttempt{}, err
	}
	return row, nil
}

// FinishAttempt commits the trace, result rows and article outcome together, once.
func FinishAttempt(ctx context.Context, db *gorm.DB, id int64, completion AttemptCompletion) error {
	if id <= 0 || completion.FinishedAt.IsZero() {
		return errors.New("attempt ID and finish time are required")
	}
	for _, count := range []*int64{completion.PromptTokens, completion.CompletionTokens, completion.TotalTokens} {
		if count != nil && *count < 0 {
			return errors.New("token counts must be absent or nonnegative")
		}
	}
	status := StatusCompleted
	articleStatus := StatusCompleted
	if completion.Result == nil {
		status = StatusFailed
		articleStatus = completion.FailureStatus
		if strings.TrimSpace(completion.Error) == "" || (articleStatus != StatusPending && articleStatus != StatusFailed) {
			return errors.New("failed attempt requires an error and pending or failed article status")
		}
	} else if completion.Error != "" || completion.FailureStatus != "" {
		return errors.New("successful attempt must not contain failure fields")
	}
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var attempt TaggingAttempt
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&attempt, id).Error; err != nil {
			return err
		}
		if attempt.Status != StatusProcessing {
			return ErrAttemptNotProcessing
		}
		if completion.FinishedAt.Before(attempt.StartedAt) {
			return errors.New("attempt finish time precedes start time")
		}
		if completion.Result != nil {
			v, err := LoadVocabulary(ctx, tx, attempt.Version)
			if err != nil {
				return err
			}
			if err := ValidateTaggingResult(v, attempt.InputText, *completion.Result); err != nil {
				return err
			}
			assignments := make([]TagAssignment, 0, len(completion.Result.Tags))
			for _, value := range completion.Result.Tags {
				assignments = append(assignments, TagAssignment{AttemptID: id, Version: attempt.Version, TagID: value.TagID, Evidence: value.Evidence})
			}
			if len(assignments) > 0 {
				if err := tx.Omit(clause.Associations).Create(&assignments).Error; err != nil {
					return err
				}
			}
			events := make([]EventInstance, 0, len(completion.Result.Events))
			for _, value := range completion.Result.Events {
				events = append(events, EventInstance{AttemptID: id, TagID: value.TagID, Status: value.Status, Evidence: value.Evidence})
			}
			if len(events) > 0 {
				if err := tx.Omit(clause.Associations).Create(&events).Error; err != nil {
					return err
				}
			}
		}
		if err := tx.Model(&attempt).Updates(map[string]any{
			"status": status, "finished_at": completion.FinishedAt.UTC(), "response": completion.Response, "error": completion.Error,
			"prompt_tokens": completion.PromptTokens, "completion_tokens": completion.CompletionTokens, "total_tokens": completion.TotalTokens,
		}).Error; err != nil {
			return err
		}
		updated := tx.Model(&Article{}).Where("id = ? AND processing_status = ?", attempt.ArticleID, StatusProcessing).Update("processing_status", articleStatus)
		if updated.Error != nil {
			return updated.Error
		}
		if updated.RowsAffected != 1 {
			return errors.New("attempt article is no longer processing")
		}
		return nil
	})
}

// ValidateTaggingResult checks the frozen contract against the exact supplied text.
// JSON shape/required-field checks belong to the response decoder, not typed storage.
func ValidateTaggingResult(v vocabulary.Vocabulary, text string, result TaggingResult) error {
	byID := make(map[string]string, len(v.Tags))
	for _, tag := range v.Tags {
		byID[tag.ID] = tag.Dimension
	}
	assigned := make(map[string]bool, len(result.Tags))
	for _, tag := range result.Tags {
		if byID[tag.TagID] == "" || assigned[tag.TagID] || strings.TrimSpace(tag.Evidence) == "" || !strings.Contains(text, tag.Evidence) {
			return errors.New("assignment has an unknown/duplicate tag or nonliteral/empty evidence")
		}
		assigned[tag.TagID] = true
	}
	eventTags := make(map[string]bool)
	type instance struct{ tagID, status, evidence string }
	seen := make(map[instance]bool)
	for _, event := range result.Events {
		status := ""
		if event.Status != nil {
			status = *event.Status
			if status != "observed" && status != "announced_planned" && status != "forecast" {
				return errors.New("event status must be observed, announced_planned, forecast or null")
			}
		}
		key := instance{event.TagID, status, event.Evidence}
		if !assigned[event.TagID] || byID[event.TagID] != "event" || strings.TrimSpace(event.Evidence) == "" || !strings.Contains(text, event.Evidence) || seen[key] {
			return errors.New("event lacks an assigned event tag or literal evidence, or duplicates an instance")
		}
		seen[key] = true
		eventTags[event.TagID] = true
	}
	for tagID := range assigned {
		if byID[tagID] == "event" && !eventTags[tagID] {
			return errors.New("event tag requires at least one event instance")
		}
	}
	return nil
}

// LoadAttempts returns complete traces, including failed/in-flight attempts, in attempt order.
func LoadAttempts(ctx context.Context, db *gorm.DB, articleID int64) ([]TaggingAttempt, error) {
	if articleID <= 0 {
		return nil, errors.New("article ID must be positive")
	}
	var attempts []TaggingAttempt
	err := db.WithContext(ctx).Where("article_id = ?", articleID).Order("number").Preload("Assignments", func(tx *gorm.DB) *gorm.DB { return tx.Order("tag_id") }).Preload("Events", func(tx *gorm.DB) *gorm.DB { return tx.Order("id") }).Find(&attempts).Error
	return attempts, err
}

type BudgetPause struct {
	ID    int `gorm:"primaryKey;autoIncrement:false;check:budget_pause_singleton,id = 1"`
	Until *time.Time
}

// SetBudgetPause persists a provider suspension; nil explicitly clears it.
func SetBudgetPause(ctx context.Context, db *gorm.DB, until *time.Time) error {
	var utc *time.Time
	if until != nil {
		if until.IsZero() {
			return errors.New("budget pause must be absent or nonzero")
		}
		value := until.UTC()
		utc = &value
	}
	return db.WithContext(ctx).Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "id"}}, DoUpdates: clause.AssignmentColumns([]string{"until"})}).Create(&BudgetPause{ID: 1, Until: utc}).Error
}

func LoadBudgetPause(ctx context.Context, db *gorm.DB) (*time.Time, error) {
	var pause BudgetPause
	err := db.WithContext(ctx).First(&pause, 1).Error
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return nil, nil
	}
	return pause.Until, err
}
